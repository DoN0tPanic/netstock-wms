"""Gli errori di integrità del database, detti come li direbbe una persona.

Il database è l'ultima difesa: un codice duplicato, una quantità a zero, un
riferimento a qualcosa che non esiste più li ferma lui anche quando il codice
dell'applicazione non ci ha pensato. Ma senza traduzione quel rifiuto arrivava
all'utente come un errore 500 — «qualcosa si è rotto» — invece che come la
cosa semplice che è: «esiste già un costruttore con questo codice».

Il beta test ne ha trovati cinque in un pomeriggio (costruttori, articoli,
bolle, utenti, righe a zero pezzi). Tradurli qui, in un punto solo, copre
anche quelli che nessuno ha ancora provato.
"""

from typing import Any

from sqlalchemy.exc import IntegrityError

# Il nome del vincolo dice esattamente cosa è stato violato: è l'informazione
# che serve per un messaggio preciso invece che generico.
_MESSAGGI: dict[str, str] = {
    "vendors_code_key": "Esiste già un costruttore con questo codice.",
    "categories_code_key": "Esiste già una categoria con questo codice.",
    "suppliers_name_key": "Esiste già un fornitore con questo nome.",
    "locations_code_key": "Esiste già un'ubicazione con questo codice.",
    "uq_catalog_vendor_pn": "Questo costruttore ha già un articolo con questo part number.",
    "uq_ddt_supplier_number": "Questo fornitore ha già una bolla con questo numero.",
    "uq_ddt_line": "Questa bolla ha già una riga con questo numero.",
    "uq_unit_item_serial": "Seriale già presente per questo articolo.",
    "extraction_templates_name_key": "Esiste già un template con questo nome.",
    "users_username_key": "Questo nome utente è già in uso.",
    "documents_sha256_key": "Questo documento è già in archivio.",
    "delivery_note_lines_qty_expected_check": "I pezzi attesi devono essere più di zero.",
    "delivery_note_lines_qty_received_check": "I pezzi ricevuti non possono essere negativi.",
    "stock_movements_quantity_check": "La quantità deve essere più di zero.",
    "ck_movement_not_self": "Partenza e destinazione coincidono.",
    "ck_movement_has_direction": "Serve un'ubicazione di partenza o di arrivo.",
    "ck_serialized_qty": "Un pezzo con seriale si muove uno alla volta.",
}

# SQLSTATE di PostgreSQL: il codice dice la famiglia dell'errore anche quando
# il vincolo non è fra quelli qui sopra.
_DUPLICATO = "23505"
_NON_AMMESSO = {"23514": "Valore non consentito.", "23502": "Manca un dato obbligatorio."}
_RIFERIMENTO = "23503"


def traduci(errore: IntegrityError) -> tuple[int, dict[str, Any]]:
    """Codice HTTP e corpo della risposta per un errore di integrità."""
    originale = errore.orig
    causa = getattr(originale, "__cause__", None)
    stato = getattr(originale, "sqlstate", None) or getattr(causa, "sqlstate", None)
    vincolo = getattr(causa, "constraint_name", None)
    dettagli = {"vincolo": vincolo} if vincolo else {}

    if stato == _DUPLICATO:
        messaggio = _MESSAGGI.get(vincolo or "", "Esiste già un elemento con questi dati.")
        return 409, _corpo("DUPLICATE", messaggio, dettagli)
    if stato == _RIFERIMENTO:
        messaggio = "Riferimento a un elemento che non esiste, o che è ancora in uso."
        return 422, _corpo("VALIDATION_ERROR", messaggio, dettagli)
    messaggio = _MESSAGGI.get(vincolo or "") or _NON_AMMESSO.get(
        stato or "", "Dati non consentiti."
    )
    return 422, _corpo("VALIDATION_ERROR", messaggio, dettagli)


def _corpo(codice: str, messaggio: str, dettagli: dict[str, Any]) -> dict[str, Any]:
    return {"error": {"code": codice, "message": messaggio, "details": dettagli}}
