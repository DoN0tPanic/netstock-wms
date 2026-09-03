"""Lettura strutturale di una bolla con un modello locale (§7.2, esteso).

La divisione dei compiti è netta, ed è la ragione per cui questo modulo esiste
separato da `document_lines.py`:

- il modello decide **dove va un dato**: dove comincia una riga, quale colonna
  è la quantità consegnata e quale l'ordinata, quale codice è del fornitore e
  quale del produttore, quali righe non sono merce;
- il modello non decide **qual è il dato**: ogni valore che restituisce deve
  comparire alla lettera nel testo OCR, altrimenti viene scartato.

Il motivo dell'asimmetria è che un seriale mancante lo digita l'operatore in
dieci secondi, mentre un seriale inventato entra nel registro append-only e da
lì non esce più.

Questo serve dove la ricerca deterministica non arriva. I casi che lo rendono
necessario, visti su bolle di distributore:

- `Bestellt … / Geliefert …`: ordinato e consegnato non coincidono, e la
  quantità giusta è il secondo. Nessuna regola di prossimità può sceglierla,
  perché entrambe le colonne sono numeri accanto al codice articolo. Il modello
  sceglie quella giusta.
- una riga in cui ogni seriale è seguito da un secondo codice fra parentesi
  (`SN2`): il doppio dei codici, tutti della stessa forma, di cui solo metà
  sono i seriali dei pezzi. Non è la norma, ma dove capita contarli tutti
  raddoppierebbe la giacenza di quella riga.
- `SPESE DI TRASPORTO`, quantità 1: una riga che non deve diventare giacenza.
"""

import json
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

import httpx
import structlog

from app.config import get_settings
from app.services import ai_config
from app.services.extraction.document_lines import CatalogItemRef

logger = structlog.get_logger("netstock.extraction.document_ai")
settings = get_settings()

SYSTEM_PROMPT = """Analizzi il testo OCR di un documento di trasporto (DDT, packing
list, Lieferschein) ed estrai la tabella degli articoli.

Come e' fatta una riga articolo: comincia con il numero di posizione, seguito dalla
quantita' ordinata, dalla quantita' consegnata, dal codice interno del fornitore
(item no / Artikel-Nr) e dalla descrizione. Sotto la descrizione compare il codice
del produttore (VPN / Hersteller Nr), spesso con un suffisso "=". Piu' sotto possono
comparire i numeri di serie, introdotti da "SN:" o "S/N".

Esempio di riga e di come va letta:

  7   10   6  881AB42   24-PORT GIGABIT SWITCH
                        WS-C2960X-24=
      SN: ABC1234WXYZ, SN: ABC1234WXZ0
  -> position "7", qty_ordered "10", qty_delivered "6", item_no "881AB42",
     vpn "WS-C2960X-24=", description "24-PORT GIGABIT SWITCH",
     serials ["ABC1234WXYZ","ABC1234WXZ0"]

Regole assolute:
1. Ogni valore deve comparire LETTERALMENTE nel testo ricevuto. Non correggere gli
   errori dell'OCR, non completare, non indovinare, non tradurre.
2. Se un dato non e' presente il valore e' "", e le liste sono vuote. Un campo vuoto
   e' una risposta corretta.
3. qty_delivered e' la quantita' CONSEGNATA (qty del. / Geliefert), qty_ordered
   quella ORDINATA (qty ord. / Bestellt). Sui documenti le due colonne differiscono
   spesso: consegnata e' quella che conta.
4. description e' solo la descrizione commerciale dell'articolo. Non ci vanno mai il
   nome del cliente, gli indirizzi, i riferimenti d'ordine (EU#, MC#, SPECIAL BID).
5. item_no va copiato carattere per carattere dal testo: serve a ritrovare la riga
   nel documento, quindi deve coincidere esattamente, anche se contiene un errore
   dell'OCR.
6. Una riga che non e' merce fisica (trasporto, spese, sconti, imballo) ha
   is_goods false.
7. Non elencare numeri di serie. Ignora del tutto le righe che cominciano con "SN:".
8. Elenca ogni riga articolo una sola volta, in ordine di posizione."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                # I vincoli non sono decorativi: senza, su una pagina rumorosa
                # il modello smette di analizzare e si mette a ricopiare il
                # testo riga per riga, sputando una "riga articolo" per ogni
                # riga del documento. La grammatica glielo impedisce — una
                # posizione può essere solo un numero, un codice non può
                # essere lungo quanto una frase.
                "properties": {
                    "position": {"type": "string", "pattern": "^[0-9]{1,3}$"},
                    "qty_ordered": {"type": "string", "pattern": "^[0-9.,]{1,9}$"},
                    "qty_delivered": {"type": "string", "pattern": "^[0-9.,]{1,9}$"},
                    "item_no": {"type": "string", "maxLength": 24},
                    "vpn": {"type": "string", "maxLength": 40},
                    "description": {"type": "string", "maxLength": 120},
                    "is_goods": {"type": "boolean"},
                },
                "required": [
                    "position", "qty_ordered", "qty_delivered", "item_no", "vpn",
                    "description", "is_goods",
                ],
            },
        }
    },
    "required": ["lines"],
}

# Forma minima perché una stringa possa essere un numero di serie. Volutamente
# larga (i seriali dei vari produttori non si somigliano), ma abbastanza stretta
# da rifiutare le frasi che un modello piccolo ogni tanto infila qui dentro:
# un modello piccolo aveva proposto come seriale un'intera riga di intestazione,
# ragione sociale del destinatario compresa.
_SERIAL_SHAPE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{4,23}$")
_CATALOG_MATCH_RATIO = 0.82

# Un seriale sul documento è sempre etichettato ("SN:", "S/N"), e su alcune bolle
# porta con sé un secondario fra parentesi — che l'OCR legge anche come graffa:
#     SN: ABC1234WXYZ (SN2: ABC1234WXZ0)
# Sono 48 codici di forma identica per 24 pezzi: solo l'etichetta distingue il
# seriale vero dal suo gemello, nessun pattern può farlo.
_SERIAL_LINE = re.compile(
    r"\bS\s*/?\s*N\s*[:.]?\s*([A-Z0-9][A-Z0-9\-]{4,23})"
    r"(?:\s*[({\[]\s*SN\s*2\s*[:.]?\s*([A-Z0-9][A-Z0-9\-]{4,23})\s*[)}\]])?",
    re.IGNORECASE,
)


@dataclass
class _SerialHit:
    position: int
    value: str
    secondary: str | None


def _scan_serials(ocr_text: str) -> list[_SerialHit]:
    """Tutti i seriali etichettati nel testo, nell'ordine in cui compaiono.

    Ogni valore è per costruzione una sottostringa letterale del testo OCR: qui
    non si genera nulla, si ritaglia soltanto.
    """
    hits: list[_SerialHit] = []
    for match in _SERIAL_LINE.finditer(ocr_text):
        value = match.group(1).upper()
        if not _SERIAL_SHAPE.match(value):
            continue
        secondary = (match.group(2) or "").upper() or None
        if secondary and not _SERIAL_SHAPE.match(secondary):
            secondary = None
        hits.append(_SerialHit(position=match.start(), value=value, secondary=secondary))
    return hits


@dataclass
class ProposedLine:
    """Una riga proposta dal modello, già verificata contro il testo OCR."""

    position: str
    description: str
    supplier_code: str | None
    part_number: str | None
    quantity: Decimal | None
    quantity_ordered: Decimal | None
    catalog_item: CatalogItemRef | None
    serials: list[str] = field(default_factory=list)
    secondary_serials: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class DocumentProposal:
    lines: list[ProposedLine] = field(default_factory=list)
    non_goods: list[str] = field(default_factory=list)
    # Seriali che compaiono prima della prima riga riconosciuta: capita sulle
    # pagine di continuazione, dove l'elenco di un articolo prosegue dalla
    # pagina precedente. Vanno mostrati, non buttati.
    unassigned_serials: list[str] = field(default_factory=list)
    model: str = ""
    duration_ms: int = 0


def _normalize_part_number(value: str) -> str:
    # I codici Cisco sulle bolle finiscono con "=" (STACK-T4-1M=), a catalogo no.
    return value.strip().upper().rstrip("=").strip()


def _match_catalog(value: str, catalog_items: list[CatalogItemRef]) -> CatalogItemRef | None:
    """Risolve un codice letto contro il catalogo reale.

    Prima l'uguaglianza, poi la somiglianza sopra una soglia alta. Mai il
    "più vicino" in assoluto: su un catalogo di switch quasi identici
    sceglierebbe con sicurezza il modello sbagliato.
    """
    needle = _normalize_part_number(value)
    if len(needle) < 4:
        return None
    for item in catalog_items:
        if _normalize_part_number(item.part_number) == needle:
            return item
    best: CatalogItemRef | None = None
    best_ratio = _CATALOG_MATCH_RATIO
    for item in catalog_items:
        ratio = SequenceMatcher(None, needle, _normalize_part_number(item.part_number)).ratio()
        if ratio > best_ratio:
            best, best_ratio = item, ratio
    return best


def _to_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9,.]", "", str(value)).replace(",", ".")
    if not cleaned:
        return None
    try:
        quantity = Decimal(cleaned)
    except InvalidOperation:
        return None
    return quantity if quantity > 0 else None


# Righe che sul documento non dicono nulla sulla struttura della tabella e che
# nel prompt fanno solo rumore: gli elenchi di seriali (che ritagliamo da soli
# con la regex), i riferimenti d'ordine ripetuti riga dopo riga, i codici a
# barre logistici. Sulla seconda pagina della bolla di prova erano due terzi del
# testo:
# lasciarle dentro sommergeva il modello, che restituiva righe vuote.
_NOISE_PREFIXES = (
    "EU#", "EUA-", "MC#", "SPECIAL BID", "EAN/UPC", "EAN/UPG",
    "ENTHALTEN IN KARTON", "CONTAINED IN BOX", "NON-RETURNABLE",
    "PACKSTUCK", "PACKSTÜCK", "TRACKING NO", "KARTON-NR", "BOX NO",
)
_SERIAL_ONLY = re.compile(r"^[\s.,;:|]*(?:S\s*/?\s*N\s*[:.]?\s*[A-Z0-9\-]+"
                          r"(?:\s*[({\[][^)}\]]*[)}\]])?[\s.,;:|]*)+$", re.IGNORECASE)


def _condense_for_model(ocr_text: str) -> str:
    """Toglie dal testo ciò che non serve a capire la struttura.

    L'ancoraggio e la ricerca dei seriali continuano a lavorare sul testo
    **originale**: qui si riduce soltanto ciò che viene mostrato al modello.
    """
    kept: list[str] = []
    for line in ocr_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if _SERIAL_ONLY.match(stripped):
            continue
        if any(upper.startswith(prefix) for prefix in _NOISE_PREFIXES):
            continue
        # Numeri lunghissimi isolati: codici a barre logistici e tracking.
        if re.fullmatch(r"[\d\s|.,]{14,}", stripped):
            continue
        kept.append(stripped)
    condensed = "\n".join(kept)
    return condensed if condensed.strip() else ocr_text


async def _call_model(ocr_text: str) -> dict:
    body = {
        "model": await ai_config.modello(),
        "system": SYSTEM_PROMPT,
        "prompt": f"Testo OCR del documento:\n---\n{_condense_for_model(ocr_text)}\n---",
        "format": RESPONSE_SCHEMA,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "top_p": 0.1,
            "num_predict": settings.extract_num_predict,
            "num_ctx": settings.extract_num_ctx,
        },
    }
    timeout = httpx.Timeout(settings.extract_timeout_seconds, connect=10.0)
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=timeout) as client:
        response = await client.post("/api/generate", json=body)
        response.raise_for_status()
        payload = response.json()
    parsed = json.loads(payload.get("response") or "{}")
    return parsed if isinstance(parsed, dict) else {}


async def propose_document_lines(
    ocr_text: str, catalog_items: list[CatalogItemRef]
) -> DocumentProposal:
    """Chiede al modello la struttura della bolla, poi riempie le righe.

    Il modello dice *dove* comincia ogni riga e cosa sono le sue colonne. I
    numeri di serie non glieli si chiede nemmeno: vengono ritagliati dal testo
    OCR con una regex e assegnati alla riga in base alla posizione, fra un
    ancoraggio e il successivo. Così un seriale non può essere inventato — al
    massimo può mancare, e un campo vuoto lo riempie l'operatore.

    Non solleva mai: se il modello non risponde, la proposta torna vuota e
    l'operatore resta con il risultato deterministico, che è già sullo schermo.
    """
    started = time.monotonic()
    proposal = DocumentProposal(model=await ai_config.modello())

    if not settings.extract_enabled or not ocr_text.strip():
        return proposal

    try:
        raw = await _call_model(ocr_text)
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("document_ai_failed", error=str(exc))
        return proposal

    upper_text = ocr_text.upper()
    serial_hits = _scan_serials(ocr_text)

    # Fase 1: ogni riga viene ancorata al punto del testo in cui compare il suo
    # codice. Una riga che non si riesce ad ancorare viene tenuta lo stesso, ma
    # senza seriali: meglio una riga da completare a mano che dei seriali
    # attribuiti al pezzo sbagliato.
    anchored: list[tuple[int, dict]] = []
    used_anchors: set[int] = set()
    search_from = 0
    rejected = 0
    for entry in raw.get("lines") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("is_goods") is False:
            description = str(entry.get("description") or "").strip()
            if description:
                proposal.non_goods.append(description)
            continue
        # L'ancoraggio procede **in avanti**: ogni riga cerca il proprio codice
        # a partire da dove è finita la precedente. Cercando sempre dall'inizio,
        # due righe con lo stesso codice finivano nello stesso punto, e un
        # modello che ripete una riga (capita) produceva una riga fantasma con
        # zero seriali accanto a quella buona — che poi impedisce di confermare,
        # perché un articolo serializzato senza seriali non si può ricevere.
        #
        # Se il codice esiste nel documento ma solo *prima* del punto raggiunto,
        # la riga è una ripetizione e si scarta: non si ripiega sull'altro
        # codice della stessa riga, che si trova pochi caratteri più avanti e
        # farebbe rientrare dalla finestra il duplicato appena uscito dalla
        # porta. Un documento che elenca davvero lo stesso articolo due volte
        # continua a funzionare, perché lì la seconda occorrenza c'è.
        codici = [
            codice
            for codice in (
                str(entry.get("item_no") or "").strip().upper(),
                str(entry.get("vpn") or "").strip().upper(),
            )
            if len(codice) >= 4
        ]
        anchor = -1
        for codice in codici:
            found = upper_text.find(codice, search_from)
            if found >= 0:
                anchor = found
                break
            if upper_text.find(codice) >= 0:
                break  # ripetizione di una riga già presa
        if anchor < 0:
            # Nessuno dei due codici della riga compare nel documento: la riga
            # non esiste. Succede quando il modello non riesce a leggere la
            # pagina e ripiega sul copiare l'esempio del prompt — cinque righe
            # "24-PORT GIGABIT SWITCH" su una bolla di switch Catalyst. Una
            # riga inventata è peggio di una riga mancante: quella mancante
            # l'operatore la vede, quella inventata la conferma.
            rejected += 1
            continue
        anchored.append((anchor, entry))
        used_anchors.add(anchor)
        search_from = anchor + 1

    # L'ordinamento è per posizione soltanto. Ordinando le coppie intere,
    # due righe ancorate allo stesso punto — il modello che ripete lo stesso
    # codice, cosa che capita — facevano confrontare i due dizionari e
    # sollevavano `TypeError`, uccidendo l'intera analisi: nessuna proposta,
    # nessuna spiegazione, solo un'attesa che non finiva.
    positioned = sorted(anchored, key=lambda coppia: coppia[0])

    for index, (anchor, entry) in enumerate(positioned):
        block_end = positioned[index + 1][0] if index + 1 < len(positioned) else len(ocr_text)
        block = [hit for hit in serial_hits if anchor <= hit.position < block_end]
        proposal.lines.append(_build_line(entry, block, upper_text, catalog_items))

    unassigned = [
        hit.value
        for hit in serial_hits
        if positioned and hit.position < positioned[0][0]
    ]
    proposal.unassigned_serials = unassigned

    proposal.duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "document_ai_done",
        lines=len(proposal.lines),
        rejected_lines=rejected,
        serials=sum(len(line.serials) for line in proposal.lines),
        duration_ms=proposal.duration_ms,
    )
    return proposal


def _build_line(
    entry: dict,
    serial_hits: list[_SerialHit],
    upper_text: str,
    catalog_items: list[CatalogItemRef],
) -> ProposedLine:
    supplier_code = str(entry.get("item_no") or "").strip() or None
    part_number = str(entry.get("vpn") or "").strip() or None

    # Anche i codici devono esistere nel testo: se il modello ne compone uno
    # mettendo insieme pezzi presi da punti diversi del documento, qui cade.
    if supplier_code and supplier_code.upper() not in upper_text:
        supplier_code = None
    if part_number and part_number.upper() not in upper_text:
        part_number = None

    item = _match_catalog(part_number, catalog_items) if part_number else None
    if item is None and supplier_code:
        item = _match_catalog(supplier_code, catalog_items)

    serials = [hit.value for hit in serial_hits]
    secondary = [hit.secondary for hit in serial_hits if hit.secondary]

    quantity = _to_decimal(entry.get("qty_delivered"))
    quantity_ordered = _to_decimal(entry.get("qty_ordered"))

    warnings: list[str] = []
    if quantity is not None and quantity_ordered is not None and quantity != quantity_ordered:
        warnings.append(
            f"Ordinati {quantity_ordered}, consegnati {quantity}: viene caricata la "
            "quantità consegnata."
        )
    if serials and quantity is not None and Decimal(len(serials)) != quantity:
        warnings.append(
            f"Nel documento ci sono {len(serials)} seriali ma la quantità consegnata è "
            f"{quantity}: controlla la riga prima di confermare."
        )
    # "non presente a catalogo" non sta fra gli avvisi: è un fatto sullo stato del
    # catalogo nel momento in cui si guarda, non sulla lettura del documento.
    # Scritto qui, restava visibile anche dopo che l'operatore aveva creato
    # l'articolo — accanto al riquadro verde che diceva l'opposto. Lo deriva chi
    # disegna, da `catalog_item`.
    if item is not None and item.is_serialized and not serials:
        warnings.append(
            "Articolo serializzato ma nessun seriale leggibile sul documento: "
            "vanno acquisiti con lo scanner."
        )

    return ProposedLine(
        position=str(entry.get("position") or "").strip(),
        description=str(entry.get("description") or "").strip(),
        supplier_code=supplier_code,
        part_number=part_number,
        quantity=quantity,
        quantity_ordered=quantity_ordered,
        catalog_item=item,
        serials=serials,
        secondary_serials=secondary,
        warnings=warnings,
    )
