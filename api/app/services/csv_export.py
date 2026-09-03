"""Come questo sistema scrive un CSV, in un posto solo.

Tre endpoint di esportazione scrivevano ciascuno il proprio `csv.writer`, e la
quarta esportazione — quella completa — sarebbe stata la quarta copia. Qui
stanno le tre decisioni che devono valere per tutte: il separatore, la firma di
codifica e come diventa testo un valore che arriva dal database.
"""
import csv
import datetime
import io
import uuid
from collections.abc import Iterable, Sequence
from decimal import Decimal
from enum import Enum
from typing import Any

from fastapi.responses import StreamingResponse

# Excel non ha modo di indovinare la codifica di un file di testo e ricade su
# quella di sistema: senza questa firma in testa, «Quantità» compare a schermo
# come «QuantitÃ». Il punto e virgola per lo stesso motivo — con la virgola,
# Excel in italiano mette l'intera riga in una cella sola.
_BOM = "\ufeff"
_DELIMITER = ";"

# I valori degli enum arrivano dal database in inglese perché è la lingua dello
# schema. In un foglio che qualcuno apre e legge, no.
CONDITION_LABELS: dict[str, str] = {
    "new": "Nuovo",
    "refurbished": "Ricondizionato",
    "used": "Usato",
    "faulty": "Guasto",
}
UNIT_STATUS_LABELS: dict[str, str] = {
    "in_stock": "In magazzino",
    "reserved": "Prenotato",
    "issued": "Consegnato",
    "in_rma": "In RMA",
    "scrapped": "Rottamato",
    "lost": "Rimosso per errore di inserimento",
}
LOCATION_TYPE_LABELS: dict[str, str] = {
    "warehouse": "Magazzino",
    "shelf": "Scaffale",
    "box": "Contenitore",
    "remote_site": "Sede remota",
    "transit": "In transito",
}
RESERVATION_STATUS_LABELS: dict[str, str] = {
    "open": "Aperta",
    "fulfilled": "Evasa",
    "cancelled": "Annullata",
    "expired": "Scaduta",
}


def cell(value: Any) -> str:
    """Un valore del database come lo si vuole leggere in un foglio di calcolo.

    Le date in ISO perché è l'unico formato che Excel interpreta uguale in
    ogni impostazione locale; i booleani in italiano perché la colonna la
    legge una persona, non un parser.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Sì" if value else "No"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def csv_text(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    buffer.write(_BOM)
    writer = csv.writer(buffer, delimiter=_DELIMITER)
    writer.writerow(headers)
    writer.writerows([cell(value) for value in row] for row in rows)
    return buffer.getvalue()


def csv_response(
    filename: str, headers: Sequence[str], rows: Iterable[Sequence[Any]]
) -> StreamingResponse:
    return StreamingResponse(
        iter([csv_text(headers, rows)]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
