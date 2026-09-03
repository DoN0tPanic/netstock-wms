"""Esportazione completa: tutto il magazzino in un archivio di CSV.

Le esportazioni per pagina esistevano già, ma per avere il quadro intero
bisognava scaricarle una per una e sapere quali fossero. Qui c'è una chiamata
sola che scrive ogni tabella in un file, con la stessa forma leggibile che
hanno a schermo.

Un archivio e non un CSV unico perché queste tabelle hanno colonne diverse:
incollarle in un file solo darebbe un foglio che nessun programma sa aprire.
"""
import io
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.inventory import INVENTORY_HEADERS, empty_filters, inventory_table
from app.api.v1.movements import MOVEMENT_HEADERS, movements_table
from app.api.v1.stock import STOCK_HEADERS, stock_table
from app.deps import CurrentUser, DbSession
from app.services.audit import write_audit
from app.services.csv_export import (
    CONDITION_LABELS,
    LOCATION_TYPE_LABELS,
    RESERVATION_STATUS_LABELS,
    csv_text,
)

router = APIRouter(prefix="/export", tags=["export"])

@dataclass(frozen=True)
class _Foglio:
    """Un file dell'archivio: come si chiama, cosa dice in testa, cosa legge.

    `enums` sono gli indici delle colonne che contengono un valore di enum del
    database, gli unici da tradurre. Tradurre a tappeto ogni stringa che
    somigli a una chiave nota trasformerebbe un'ubicazione di codice «BOX» nel
    suo significato, che è precisamente il modo di rovinare un'esportazione.
    """

    filename: str
    headers: str
    query: str
    enums: tuple[int, ...] = field(default_factory=tuple)


# Le tabelle che si leggono direttamente, con l'intestazione già in italiano.
# Le tre grandi — giacenze, disponibilità e movimenti — non stanno qui: sono
# le stesse funzioni che servono gli export di pagina, importate sopra, così
# l'archivio non può divergere da quello che si scarica dalle singole schermate.
_FOGLI: tuple[_Foglio, ...] = (
    _Foglio(
        "catalogo.csv",
        "Codice articolo;Nome;Vendor;Categoria;Serializzato;Unità di misura;"
        "Punto di riordino;Fine vita;Fine supporto;Formato seriale;Attivo;Note",
        """
        SELECT ci.part_number, ci.name, v.code, c.code, ci.is_serialized, ci.uom,
               ci.reorder_point, ci.eol_date, ci.eos_date, ci.serial_pattern,
               ci.is_active, ci.notes
        FROM catalog_items ci
        JOIN vendors v ON v.id = ci.vendor_id
        JOIN categories c ON c.id = ci.category_id
        ORDER BY ci.part_number
        """,
    ),
    _Foglio(
        "bolle.csv",
        "Numero;Data;Fornitore;Ordine;Corriere;Tracking;Ricevuta il;Ricevuta da;Chiusa;Note",
        """
        SELECT dn.number, dn.note_date, s.name, dn.po_number, dn.carrier, dn.tracking_number,
               dn.received_at, u.username, dn.is_closed, dn.notes
        FROM delivery_notes dn
        JOIN suppliers s ON s.id = dn.supplier_id
        JOIN users u ON u.id = dn.received_by
        ORDER BY dn.note_date DESC, dn.number
        """,
    ),
    _Foglio(
        "bolle-righe.csv",
        "Bolla;Riga;Codice articolo;Nome;Attese;Ricevute;Condizione;Note",
        """
        SELECT dn.number, dnl.line_number, ci.part_number, ci.name,
               dnl.qty_expected, dnl.qty_received, dnl.condition, dnl.notes
        FROM delivery_note_lines dnl
        JOIN delivery_notes dn ON dn.id = dnl.delivery_note_id
        JOIN catalog_items ci ON ci.id = dnl.catalog_item_id
        ORDER BY dn.number, dnl.line_number
        """,
        enums=(6,),
    ),
    _Foglio(
        "ubicazioni.csv",
        "Codice;Nome;Tipo;Dentro;Indirizzo;Attiva",
        """
        SELECT l.code, l.name, l.type, p.code, l.address, l.is_active
        FROM locations l
        LEFT JOIN locations p ON p.id = l.parent_id
        ORDER BY l.code
        """,
        enums=(2,),
    ),
    _Foglio(
        "prenotazioni.csv",
        "Riferimento;Richiesta da;Codice articolo;Seriale;Quantità;Ubicazione;Stato;"
        "Scade il;Creata da;Creata il;Note",
        """
        SELECT r.reference, r.requested_by, ci.part_number, su.serial_number, r.quantity,
               l.code, r.status, r.expires_at, u.username, r.created_at, r.notes
        FROM reservations r
        JOIN catalog_items ci ON ci.id = r.catalog_item_id
        LEFT JOIN stock_units su ON su.id = r.stock_unit_id
        LEFT JOIN locations l ON l.id = r.location_id
        JOIN users u ON u.id = r.created_by
        ORDER BY r.created_at DESC
        """,
        enums=(6,),
    ),
    _Foglio(
        "fornitori.csv",
        "Nome;Partita IVA;Riferimento;Attivo;Note",
        "SELECT name, vat_number, contact_ref, is_active, notes FROM suppliers ORDER BY name",
    ),
    _Foglio(
        "vendor.csv",
        "Codice;Nome;Attivo;Note",
        "SELECT code, name, is_active, notes FROM vendors ORDER BY code",
    ),
    _Foglio(
        "categorie.csv",
        "Codice;Nome;Dentro",
        """
        SELECT c.code, c.name, p.code
        FROM categories c
        LEFT JOIN categories p ON p.id = c.parent_id
        ORDER BY c.code
        """,
    ),
)

# Gli enum che compaiono nelle query qui sopra, tradotti come a schermo. Le
# chiavi sono i valori del database; quello che non è qui passa com'è.
_LABELS: dict[str, str] = {
    **CONDITION_LABELS,
    **LOCATION_TYPE_LABELS,
    **RESERVATION_STATUS_LABELS,
}


async def _sheet(db: AsyncSession, foglio: _Foglio) -> str:
    result = await db.execute(text(foglio.query))
    rows = [
        [_LABELS.get(v, v) if i in foglio.enums and isinstance(v, str) else v
         for i, v in enumerate(row)]
        for row in result
    ]
    return csv_text(foglio.headers.split(";"), rows)


def _readme(files: Sequence[str], generated_at: datetime, username: str) -> str:
    elenco = "\n".join(f"  - {name}" for name in files)
    return (
        "Esportazione completa NetStock\n"
        "=============================\n\n"
        f"Generata il {generated_at.astimezone().strftime('%d/%m/%Y alle %H:%M')} "
        f"da {username}.\n\n"
        "File contenuti:\n"
        f"{elenco}\n\n"
        "I file sono CSV separati da punto e virgola, codificati in UTF-8 con firma\n"
        "iniziale: si aprono con un doppio clic in Excel e in LibreOffice senza\n"
        "impostare niente. Le date sono in formato ISO (2026-09-01) perché è l'unico\n"
        "che i fogli di calcolo interpretano allo stesso modo in ogni lingua.\n\n"
        "Questa è una copia di lettura, non un backup: non contiene le password, le\n"
        "sessioni né il registro di sicurezza, e non si può reimportare. Il backup\n"
        "vero è il dump del database (scripts/backup.sh).\n"
    )


@router.get("")
async def export_everything(db: DbSession, user: CurrentUser) -> Any:
    """Tutto il magazzino in un archivio ZIP di CSV."""
    now = datetime.now(UTC)
    sheets: dict[str, str] = {
        "giacenze.csv": csv_text(
            INVENTORY_HEADERS, await inventory_table(db, empty_filters())
        ),
        "disponibilita.csv": csv_text(STOCK_HEADERS, await stock_table(db)),
        "movimenti.csv": csv_text(MOVEMENT_HEADERS, await movements_table(db)),
    }
    for foglio in _FOGLI:
        sheets[foglio.filename] = await _sheet(db, foglio)
    sheets["LEGGIMI.txt"] = _readme(sorted(sheets), now, user.username)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in sheets.items():
            archive.writestr(filename, content.encode("utf-8"))
    buffer.seek(0)

    # Una riga sola per un'esportazione integrale: è rara, e sapere chi ha
    # portato fuori l'intero magazzino e quando è esattamente il genere di
    # cosa per cui il registro esiste.
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="export.all",
        details={"files": sorted(sheets)},
    )

    name = f"netstock-{now.astimezone().strftime('%Y%m%d-%H%M')}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={name}"},
    )
