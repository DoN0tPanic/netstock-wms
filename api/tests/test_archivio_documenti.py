"""Archivio delle bolle: si cerca dentro, non nel nome del file.

Il caso che questa funzione esiste per risolvere: il file si chiama
`scan-esempio-001.pdf` e dentro c'è il numero d'ordine. Cercare per nome non
porta da nessuna parte.

I PDF di prova si generano qui, non stanno nel repository: un documento vero
non entra fra i sorgenti (§7.5), e uno finto committato è comunque un file
binario che nessuno rilegge.
"""

import uuid

import pytest
from sqlalchemy import select

from app.api.v1.documents import carica, elenco, elimina, file_originale
from app.api.v1.documents import testo_estratto as leggi_testo
from app.exceptions import NotFoundError, ValidationAppError
from app.models.documents import Document
from app.models.enums import UserRole
from app.models.users import User
from app.services import documents_archive


def _pdf(testo: str) -> bytes:
    """Un PDF con un livello di testo, costruito a mano.

    Meno di mezzo kilobyte e nessuna libreria di scrittura: serve a provare
    che il testo dentro un PDF si trova, non a fare tipografia. Costruirlo
    qui evita anche di committare un file binario nel repository.
    """
    fuga = testo.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    flusso = f"BT /F1 12 Tf 50 700 Td ({fuga}) Tj ET".encode("latin-1", "replace")
    oggetti = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(flusso)).encode() + b" >>\nstream\n" + flusso + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    fuori = bytearray(b"%PDF-1.4\n")
    posizioni = []
    for numero, corpo in enumerate(oggetti, start=1):
        posizioni.append(len(fuori))
        fuori += str(numero).encode() + b" 0 obj\n" + corpo + b"\nendobj\n"
    inizio_xref = len(fuori)
    fuori += b"xref\n0 " + str(len(oggetti) + 1).encode() + b"\n0000000000 65535 f \n"
    for posizione in posizioni:
        fuori += f"{posizione:010d} 00000 n \n".encode()
    fuori += (b"trailer\n<< /Size " + str(len(oggetti) + 1).encode() +
              b" /Root 1 0 R >>\nstartxref\n" + str(inizio_xref).encode() + b"\n%%EOF\n")
    return bytes(fuori)


class _FintoFile:
    """Il minimo che serve al router: un `UploadFile` con un nome e dei byte."""

    def __init__(self, nome: str, dati: bytes) -> None:
        self.filename = nome
        self.content_type = "application/pdf"
        self._dati = dati

    async def read(self) -> bytes:
        return self._dati


async def _utente(db) -> User:
    return (
        await db.execute(select(User).where(User.role == UserRole.admin).limit(1))
    ).scalars().first()


async def test_si_trova_per_contenuto_non_per_nome(app_db_session) -> None:
    """Il cuore della funzione: nome inutile, contenuto cercabile."""
    utente = await _utente(app_db_session)
    numero = f"20{uuid.uuid4().int % 10000:04d}"
    nome = f"pdf{uuid.uuid4().hex[:3]}.pdf"

    documento = await carica(
        app_db_session,
        file=_FintoFile(nome, _pdf(f"Bolla di consegna\nn ordine {numero}\nGrazie")),
        note=None,
        delivery_note_id=None,
        user=utente,
    )
    assert documento.extraction_method == "testo"

    trovati = await elenco(app_db_session, utente, q=numero)

    assert trovati.total == 1
    assert trovati.items[0].filename == nome


async def test_si_trova_anche_un_frammento_del_numero(app_db_session) -> None:
    # Un numero letto una volta si ricorda a metà: la ricerca a parole intere
    # da sola non basterebbe.
    utente = await _utente(app_db_session)
    numero = f"9911{uuid.uuid4().int % 1000:03d}"
    await carica(
        app_db_session,
        file=_FintoFile("scansione.pdf", _pdf(f"documento di trasporto {numero}")),
        note=None, delivery_note_id=None, user=utente,
    )

    trovati = await elenco(app_db_session, utente, q=numero[2:8])

    assert trovati.total >= 1


async def test_lo_stesso_file_non_entra_due_volte(app_db_session) -> None:
    # Chi scansiona ricarica per sbaglio: due copie della stessa bolla sono
    # peggio di zero, perché non si sa quale sia quella buona.
    utente = await _utente(app_db_session)
    dati = _pdf(f"bolla doppia {uuid.uuid4().hex[:8]}")
    await carica(app_db_session, file=_FintoFile("primo.pdf", dati), note=None,
                 delivery_note_id=None, user=utente)

    with pytest.raises(ValidationAppError) as rifiuto:
        await carica(app_db_session, file=_FintoFile("secondo-nome.pdf", dati), note=None,
                     delivery_note_id=None, user=utente)

    assert "già in archivio" in rifiuto.value.message


async def test_solo_pdf(app_db_session) -> None:
    utente = await _utente(app_db_session)
    with pytest.raises(ValidationAppError):
        await carica(app_db_session, file=_FintoFile("foto.png", b"\x89PNG\r\n\x1a\n non un pdf"),
                     note=None, delivery_note_id=None, user=utente)


async def test_un_file_enorme_viene_rifiutato() -> None:
    grande = b"%PDF-" + b"0" * (documents_archive.LIMITE_BYTE + 1)
    with pytest.raises(ValidationAppError) as rifiuto:
        documents_archive.leggi(grande, "application/pdf")
    assert "MB" in rifiuto.value.message


async def test_il_testo_letto_si_può_rileggere(app_db_session) -> None:
    """Serve a capire perché una ricerca non trova.

    Su una scansione storta l'OCR sbaglia: leggendo quello che il sistema ha
    davvero letto si distingue un problema di lettura da uno di ricerca.
    """
    utente = await _utente(app_db_session)
    documento = await carica(
        app_db_session,
        file=_FintoFile("bolla.pdf", _pdf(
            "Documento di trasporto - numero ordine 445566 - cliente di esempio - "
            "consegna presso magazzino"
        )),
        note=None, delivery_note_id=None, user=utente,
    )

    letto = await leggi_testo(documento.id, app_db_session, utente)

    assert "445566" in letto["text"]
    assert letto["extraction_method"] == "testo"


async def test_l_archivio_non_finisce_nella_ricerca_globale(app_db_session) -> None:
    """La sezione è stagna per scelta.

    La ricerca globale porta dritto a un pezzo in magazzino; l'archivio cerca
    dentro documenti che citano qualunque cosa. Mescolarli vorrebbe dire che
    cercare un seriale restituisce anche ogni bolla che lo nomina di sfuggita.
    """
    from app.api.v1.search import global_search

    utente = await _utente(app_db_session)
    numero = f"7788{uuid.uuid4().int % 1000:03d}"
    await carica(
        app_db_session,
        file=_FintoFile("riservato.pdf", _pdf(f"ordine {numero}")),
        note=None, delivery_note_id=None, user=utente,
    )

    globale = await global_search(app_db_session, utente, q=numero)

    assert globale["results"] == []


async def test_solo_gli_amministratori_cancellano(app_db_session) -> None:
    utente = await _utente(app_db_session)
    documento = await carica(
        app_db_session,
        file=_FintoFile("da-togliere.pdf", _pdf(f"bolla {uuid.uuid4().hex[:6]}")),
        note=None, delivery_note_id=None, user=utente,
    )

    await elimina(documento.id, app_db_session, utente)

    assert await app_db_session.get(Document, documento.id) is None
    with pytest.raises(NotFoundError):
        await elimina(documento.id, app_db_session, utente)


async def test_si_guarda_in_una_scheda_o_si_salva_una_copia(app_db_session) -> None:
    """Aprire e scaricare sono due gesti diversi, e li distingue il server.

    Un browser con lettore di PDF incorporato, davanti allo stesso link, apre
    invece di salvare: la copia la ottiene solo `attachment`.
    """
    utente = await _utente(app_db_session)
    dati = _pdf(f"bolla {uuid.uuid4().hex[:6]}")
    documento = await carica(
        app_db_session,
        file=_FintoFile("bolla-di-prova.pdf", dati),
        note=None, delivery_note_id=None, user=utente,
    )

    aperto = await file_originale(documento.id, app_db_session, utente)
    salvato = await file_originale(documento.id, app_db_session, utente, scarica=True)

    assert aperto.headers["content-disposition"].startswith("inline;")
    assert salvato.headers["content-disposition"].startswith("attachment;")
    assert salvato.body == dati  # una copia, non una rielaborazione


async def test_un_nome_impossibile_non_rompe_la_risposta(app_db_session) -> None:
    """Il nome del file finisce in un'intestazione HTTP, che è latin-1.

    Un nome con una virgoletta spezzerebbe l'intestazione, uno con caratteri
    fuori da latin-1 farebbe fallire l'invio della risposta. Il nome vero
    viaggia percentificato in `filename*`; quello fra virgolette è un ripiego.
    """
    utente = await _utente(app_db_session)
    documento = await carica(
        app_db_session,
        file=_FintoFile('bolla "нет"; città.pdf', _pdf(f"bolla {uuid.uuid4().hex[:6]}")),
        note=None, delivery_note_id=None, user=utente,
    )

    risposta = await file_originale(documento.id, app_db_session, utente, scarica=True)
    disposizione = risposta.headers["content-disposition"]

    disposizione.encode("latin-1")  # è ciò che farebbe il server inviandola
    assert disposizione.count('"') == 2
    assert "filename*=UTF-8''" in disposizione
    assert "%D0%BD%D0%B5%D1%82" in disposizione  # il nome vero, per intero
