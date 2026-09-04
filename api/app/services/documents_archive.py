"""Archivio delle bolle scansionate: conservare, e ritrovare per contenuto.

Il problema che risolve è vecchio quanto le bolle di carta: il file si chiama
`scan-esempio-001.pdf` e dentro c'è il numero d'ordine che serve. Cercare per
nome non porta da nessuna parte; cercare per contenuto sì.

Il testo si prende in due modi, in quest'ordine:

1. **Il livello di testo del PDF.** Le bolle che arrivano per posta sono PDF
   digitali: il testo è già lì, esatto, e leggerlo costa millisecondi.
2. **L'OCR**, solo se il primo non ha trovato niente. È il caso della bolla
   fotocopiata o fotografata, dove il PDF contiene un'immagine e basta. Costa
   secondi per pagina e sbaglia qualche carattere, ma è l'unica strada.

Quale dei due sia stato usato resta scritto sul documento. Serve quando una
ricerca non trova: su una scansione storta l'OCR sbaglia, e saperlo cambia
cosa si fa dopo — si cerca un frammento più corto invece di concludere che il
documento non c'è.
"""

import hashlib
import io

import pypdfium2 as pdfium
import structlog

from app.exceptions import ValidationAppError
from app.services.extraction.documents import to_pages
from app.services.extraction.ocr import run_ocr

# Una bolla scansionata sta in pochi megabyte. Oltre, o è una scansione a
# risoluzione inutile o non è una bolla: in entrambi i casi è meglio dirlo
# adesso che riempire il database.
LIMITE_BYTE = 25 * 1024 * 1024
# Il testo indicizzato ha un tetto: una bolla di venti pagine è normale, un
# catalogo di cinquecento no, e l'indice di ricerca non deve diventare il
# pezzo più pesante della tabella.
LIMITE_TESTO = 200_000
PAGINE_MASSIME_OCR = 10
# Sotto questa soglia il livello di testo non è un livello di testo: sono i
# quattro caratteri che un generatore di PDF lascia in un angolo.
SOGLIA_TESTO_UTILE = 40

_log = structlog.get_logger("netstock.archivio")


# L'anteprima serve a riconoscere una bolla a colpo d'occhio in una griglia,
# non a leggerla: 480 pixel di larghezza bastano, e un JPEG di quella misura
# pesa poche decine di kilobyte contro i megabyte del PDF.
LARGHEZZA_ANTEPRIMA = 480
QUALITA_ANTEPRIMA = 72


def anteprima(dati: bytes) -> bytes | None:
    """La prima pagina come immagine, o niente se il PDF non si lascia disegnare.

    Non solleva: un documento che non si può disegnare resta un documento
    archiviato e cercabile, semplicemente senza faccia. Fermare il caricamento
    per un'anteprima sarebbe il classico dettaglio che impedisce la cosa
    importante.
    """
    try:
        documento = pdfium.PdfDocument(io.BytesIO(dati))
        try:
            if len(documento) == 0:
                return None
            pagina = documento[0]
            larghezza = pagina.get_width() or LARGHEZZA_ANTEPRIMA
            scala = min(2.0, max(0.4, LARGHEZZA_ANTEPRIMA / larghezza))
            immagine = pagina.render(scale=scala, grayscale=False).to_pil()
        finally:
            documento.close()
        fuori = io.BytesIO()
        immagine.convert("RGB").save(
            fuori, "JPEG", quality=QUALITA_ANTEPRIMA, optimize=True
        )
        return fuori.getvalue()
    except Exception as errore:
        _log.warning("anteprima_non_riuscita", errore=str(errore)[:200])
        return None


def impronta(dati: bytes) -> str:
    return hashlib.sha256(dati).hexdigest()


def _testo_dal_livello(dati: bytes) -> tuple[str, int]:
    """Il testo già presente nel PDF, e quante pagine ha."""
    documento = pdfium.PdfDocument(io.BytesIO(dati))
    try:
        pezzi = []
        for indice in range(len(documento)):
            pagina = documento[indice]
            testo = pagina.get_textpage()
            try:
                pezzi.append(testo.get_text_range())
            finally:
                testo.close()
        return "\n".join(pezzi).strip(), len(documento)
    finally:
        # pypdfium2 tiene un handle nativo: senza close i byte del documento
        # restano vivi oltre la richiesta.
        documento.close()


def _testo_da_ocr(dati: bytes, tipo: str | None) -> str:
    pagine = to_pages(dati, tipo)[:PAGINE_MASSIME_OCR]
    return "\n".join(run_ocr(pagina, "delivery_note") for pagina in pagine).strip()


def leggi(dati: bytes, tipo: str | None) -> tuple[str, str, int | None]:
    """Il testo di un documento, come è stato ottenuto, e le sue pagine.

    Non solleva se il testo non si trova: un documento illeggibile si archivia
    lo stesso — resta il file, e si ritrova per nome o per nota. Rifiutarlo
    vorrebbe dire perderlo del tutto.
    """
    if not dati:
        raise ValidationAppError("Il file è vuoto.")
    if len(dati) > LIMITE_BYTE:
        raise ValidationAppError(
            f"Il file supera i {LIMITE_BYTE // (1024 * 1024)} MB consentiti per documento."
        )
    if dati[:5] != b"%PDF-":
        raise ValidationAppError("L'archivio accetta solo file PDF.")

    pagine: int | None = None
    try:
        testo, pagine = _testo_dal_livello(dati)
    except Exception as errore:
        _log.warning("livello_testo_illeggibile", errore=str(errore)[:200])
        testo = ""

    if len(testo) >= SOGLIA_TESTO_UTILE:
        return testo[:LIMITE_TESTO], "testo", pagine

    try:
        testo_ocr = _testo_da_ocr(dati, tipo)
    except Exception as errore:
        _log.warning("ocr_fallito", errore=str(errore)[:200])
        return testo[:LIMITE_TESTO], "nessuno", pagine

    if testo_ocr:
        return testo_ocr[:LIMITE_TESTO], "ocr", pagine
    return testo[:LIMITE_TESTO], "nessuno", pagine
