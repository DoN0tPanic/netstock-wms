import io
import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import CurrentUser, DbSession
from app.schemas.common import Page
from app.schemas.inventory import InventoryRow
from app.services.csv_export import CONDITION_LABELS, UNIT_STATUS_LABELS, csv_response

router = APIRouter(prefix="/inventory", tags=["inventory"])

_COMBINED_CTE = """
    WITH combined AS (
        SELECT
            'unit' AS kind,
            su.id::text AS row_key,
            su.catalog_item_id,
            ci.part_number,
            ci.name,
            v.code AS vendor_code,
            c.code AS category_code,
            su.location_id,
            l.code AS location_code,
            l.name AS location_name,
            su.condition::text AS condition,
            su.serial_number,
            su.mac_address::text AS mac_address,
            su.status::text AS status,
            dn.number AS delivery_note_number,
            su.warranty_end,
            su.purchase_date,
            su.contract_ref,
            su.notes,
            NULL::numeric AS quantity,
            ci.vendor_id,
            ci.category_id,
            dn.id AS delivery_note_id
        FROM stock_units su
        JOIN catalog_items ci ON ci.id = su.catalog_item_id
        JOIN vendors v ON v.id = ci.vendor_id
        JOIN categories c ON c.id = ci.category_id
        LEFT JOIN locations l ON l.id = su.location_id
        LEFT JOIN delivery_note_lines dnl ON dnl.id = su.delivery_note_line_id
        LEFT JOIN delivery_notes dn ON dn.id = dnl.delivery_note_id

        UNION ALL

        SELECT
            'bulk' AS kind,
            ci.id::text || ':' || COALESCE(sb.location_id::text, 'ext') || ':' || sb.condition::text AS row_key,
            ci.id AS catalog_item_id,
            ci.part_number,
            ci.name,
            v.code AS vendor_code,
            c.code AS category_code,
            sb.location_id,
            l.code AS location_code,
            l.name AS location_name,
            sb.condition::text AS condition,
            NULL AS serial_number,
            NULL AS mac_address,
            NULL AS status,
            NULL AS delivery_note_number,
            NULL::date AS warranty_end,
            NULL::date AS purchase_date,
            NULL AS contract_ref,
            NULL AS notes,
            sb.quantity,
            ci.vendor_id,
            ci.category_id,
            NULL::uuid AS delivery_note_id
        FROM v_stock_balance sb
        JOIN catalog_items ci ON ci.id = sb.catalog_item_id AND ci.is_serialized = FALSE
        JOIN vendors v ON v.id = ci.vendor_id
        JOIN categories c ON c.id = ci.category_id
        LEFT JOIN locations l ON l.id = sb.location_id
    )
"""

_FILTER_CLAUSE = """
    WHERE (
        CAST(:q AS text) IS NULL
        OR serial_number ILIKE '%' || CAST(:q AS text) || '%'
        OR mac_address ILIKE '%' || CAST(:q AS text) || '%'
        OR part_number ILIKE '%' || CAST(:q AS text) || '%'
        OR delivery_note_number ILIKE '%' || CAST(:q AS text) || '%'
    )
    AND (CAST(:location_id AS uuid) IS NULL OR location_id = CAST(:location_id AS uuid))
    AND (CAST(:vendor_id AS uuid) IS NULL OR vendor_id = CAST(:vendor_id AS uuid))
    AND (CAST(:category_id AS uuid) IS NULL OR category_id = CAST(:category_id AS uuid))
    AND (CAST(:condition AS text) IS NULL OR condition = CAST(:condition AS text))
    AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
    AND (CAST(:delivery_note_id AS uuid) IS NULL OR delivery_note_id = CAST(:delivery_note_id AS uuid))
"""


def _build_params(
    q: str | None,
    location: uuid.UUID | None,
    vendor: uuid.UUID | None,
    category: uuid.UUID | None,
    condition: str | None,
    status: str | None,
    delivery_note: uuid.UUID | None,
) -> dict[str, Any]:
    return {
        "q": q,
        "location_id": str(location) if location else None,
        "vendor_id": str(vendor) if vendor else None,
        "category_id": str(category) if category else None,
        "condition": condition,
        "status": status,
        "delivery_note_id": str(delivery_note) if delivery_note else None,
    }


@router.get("", response_model=Page[InventoryRow])
async def list_inventory(
    db: DbSession,
    user: CurrentUser,
    q: str | None = None,
    location: uuid.UUID | None = None,
    vendor: uuid.UUID | None = None,
    category: uuid.UUID | None = None,
    condition: str | None = None,
    status: str | None = None,
    delivery_note: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 50,
) -> Any:
    page_size = min(page_size, 200)
    params = _build_params(q, location, vendor, category, condition, status, delivery_note)

    total = (
        await db.execute(
            text(f"{_COMBINED_CTE} SELECT count(*) FROM combined {_FILTER_CLAUSE}"), params
        )
    ).scalar_one()

    result = await db.execute(
        text(
            f"{_COMBINED_CTE} SELECT * FROM combined {_FILTER_CLAUSE} "
            "ORDER BY part_number, serial_number NULLS LAST "
            "LIMIT :page_size OFFSET :offset"
        ),
        {**params, "page_size": page_size, "offset": (page - 1) * page_size},
    )
    items = [dict(row._mapping) for row in result]
    return Page(items=items, total=total, page=page, page_size=page_size)


# L'esportazione porta fuori **tutto** quello che il magazzino sa di una riga,
# non le colonne che si stanno guardando: a schermo si sceglie cosa vedere,
# in un file si prende tutto perché non si sa cosa servirà a chi lo apre.
# «Ubicazione» resta il codice — è la colonna con cui l'import riconosce
# l'ubicazione, e cambiarla romperebbe il giro esporta-correggi-reimporta —
# e il nome per esteso si aggiunge accanto.
INVENTORY_HEADERS = [
    "Tipo",
    "Codice articolo",
    "Nome",
    "Fornitore",
    "Categoria",
    "Ubicazione",
    "Nome ubicazione",
    "Condizione",
    "Seriale",
    "MAC",
    "Stato",
    "Bolla",
    "Garanzia",
    "Data acquisto",
    "Riferimento contratto",
    "Note",
    "Quantità",
]


async def inventory_table(db: AsyncSession, params: dict[str, Any]) -> list[list[Any]]:
    """Il magazzino riga per riga, pronto da scrivere.

    `params` sono gli stessi filtri della pagina: l'esportazione completa
    passa un filtro vuoto e prende tutto.
    """
    result = await db.execute(
        text(
            f"{_COMBINED_CTE} SELECT * FROM combined {_FILTER_CLAUSE} ORDER BY part_number, serial_number NULLS LAST"
        ),
        params,
    )
    return [
        [
            "Unità" if r["kind"] == "unit" else "Sfuso",
            r["part_number"],
            r["name"],
            r["vendor_code"],
            r["category_code"],
            r["location_code"] or "",
            r["location_name"] or "",
            # Le condizioni e gli stati arrivano dal database in inglese, che è
            # la lingua dello schema: in un foglio che si apre e si legge, no.
            CONDITION_LABELS.get(r["condition"], r["condition"]),
            r["serial_number"] or "",
            r["mac_address"] or "",
            UNIT_STATUS_LABELS.get(r["status"], r["status"] or ""),
            r["delivery_note_number"] or "",
            r["warranty_end"].isoformat() if r["warranty_end"] else "",
            r["purchase_date"].isoformat() if r["purchase_date"] else "",
            r["contract_ref"] or "",
            r["notes"] or "",
            float(r["quantity"]) if r["quantity"] is not None else "",
        ]
        for r in (dict(row._mapping) for row in result)
    ]


@router.get("/export")
async def export_inventory(
    db: DbSession,
    user: CurrentUser,
    format: str = "csv",
    q: str | None = None,
    location: uuid.UUID | None = None,
    vendor: uuid.UUID | None = None,
    category: uuid.UUID | None = None,
    condition: str | None = None,
    status: str | None = None,
    delivery_note: uuid.UUID | None = None,
) -> Any:
    params = _build_params(q, location, vendor, category, condition, status, delivery_note)
    data_rows = await inventory_table(db, params)

    if format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Giacenze"
        sheet.append(INVENTORY_HEADERS)
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

    return csv_response("giacenze.csv", INVENTORY_HEADERS, data_rows)


def empty_filters() -> dict[str, Any]:
    """Nessun filtro: è quello che serve all'esportazione completa."""
    return _build_params(None, None, None, None, None, None, None)
