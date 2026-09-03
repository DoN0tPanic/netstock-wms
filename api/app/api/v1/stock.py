import io
import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import CurrentUser, DbSession
from app.schemas.stock import StockBalanceResponse
from app.services.csv_export import csv_response

router = APIRouter(prefix="/stock", tags=["stock"])

AVAILABILITY_QUERY = """
    SELECT catalog_item_id, part_number, name, vendor_code, category_code,
           is_serialized, reorder_point, qty_on_hand, qty_reserved, qty_available,
           below_reorder_point
    FROM v_item_availability v
    WHERE EXISTS (
        SELECT 1 FROM catalog_items ci WHERE ci.id = v.catalog_item_id AND ci.is_active
      )
      AND (CAST(:category AS text) IS NULL OR category_code = CAST(:category AS text))
      AND (
        CAST(:below_reorder AS boolean) IS NULL
        OR below_reorder_point = CAST(:below_reorder AS boolean)
      )
    ORDER BY part_number
"""


@router.get("", response_model=list[StockBalanceResponse])
async def get_stock(
    db: DbSession,
    user: CurrentUser,
    category: str | None = None,
    below_reorder: bool | None = None,
) -> Any:
    result = await db.execute(
        text(AVAILABILITY_QUERY), {"category": category, "below_reorder": below_reorder}
    )
    return [dict(row._mapping) for row in result]


@router.get("/by-location")
async def get_stock_by_location(
    db: DbSession, user: CurrentUser, location: uuid.UUID | None = None
) -> Any:
    query = """
        SELECT sb.catalog_item_id, ci.part_number, ci.name, sb.location_id,
               l.code AS location_code, l.name AS location_name,
               sb.condition, sb.quantity
        FROM v_stock_balance sb
        JOIN catalog_items ci ON ci.id = sb.catalog_item_id
        LEFT JOIN locations l ON l.id = sb.location_id
        WHERE (CAST(:location AS uuid) IS NULL OR sb.location_id = CAST(:location AS uuid))
        ORDER BY l.code, ci.part_number
    """
    result = await db.execute(text(query), {"location": str(location) if location else None})
    return [dict(row._mapping) for row in result]


STOCK_HEADERS = [
    "Codice articolo",
    "Nome",
    "Fornitore",
    "Categoria",
    "Giacenza",
    "Prenotato",
    "Disponibile",
    "Sotto soglia",
]


async def stock_table(db: AsyncSession) -> list[list[Any]]:
    """Le righe della disponibilità per articolo, pronte da scrivere.

    Sta fuori dall'endpoint perché la stessa tabella finisce sia nel CSV di
    questa pagina sia nell'esportazione completa: due copie divergerebbero
    alla prima colonna aggiunta.
    """
    result = await db.execute(text(AVAILABILITY_QUERY), {"category": None, "below_reorder": None})
    return [
        [
            r["part_number"],
            r["name"],
            r["vendor_code"],
            r["category_code"],
            float(r["qty_on_hand"]),
            float(r["qty_reserved"]),
            float(r["qty_available"]),
            # Il testo, non il booleano: questa stessa riga finisce anche in un
            # foglio Excel, dove un bool diventerebbe VERO/FALSO.
            "Sì" if r["below_reorder_point"] else "No",
        ]
        for r in (dict(row._mapping) for row in result)
    ]


@router.get("/export")
async def export_stock(db: DbSession, user: CurrentUser, format: str = "csv") -> Any:
    data_rows = await stock_table(db)

    if format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Giacenze"
        sheet.append(STOCK_HEADERS)
        for data_row in data_rows:
            sheet.append(data_row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=giacenze.xlsx"},
        )

    return csv_response("giacenze.csv", STOCK_HEADERS, data_rows)
