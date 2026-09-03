from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.api.v1.stock import AVAILABILITY_QUERY
from app.deps import CurrentUser, DbSession
from app.models.delivery import DeliveryNote
from app.models.enums import UnitStatus, UserRole
from app.models.movements import StockMovement
from app.models.stock import StockUnit
from app.schemas.dashboard import DashboardResponse

router = APIRouter(tags=["dashboard"])

RECENT_MOVEMENTS_LIMIT = 20
EXPIRING_WARRANTIES_LIMIT = 100
WARRANTY_HORIZON_DAYS = 60

# Ordinato per quantità: un grafico a barre si legge dal più alto al più basso,
# e il nome della categoria serve perché "PSU" su un asse non dice niente a chi
# non ha in testa i codici.
_CATEGORY_TOTALS_QUERY = """
    SELECT v.category_code,
           COALESCE(MAX(c.name), v.category_code) AS category_name,
           SUM(v.qty_on_hand) AS quantity
    FROM v_item_availability v
    LEFT JOIN categories c ON c.code = v.category_code
    GROUP BY v.category_code
    HAVING SUM(v.qty_on_hand) > 0
    ORDER BY SUM(v.qty_on_hand) DESC, v.category_code
"""

# Joined to names because an anomaly identified only by UUIDs tells the admin
# nothing about which model, in which location, is out of step.
_RECONCILIATION_QUERY = """
    SELECT e.catalog_item_id, e.location_id, e.qty_ledger, e.qty_projection,
           ci.part_number, ci.name AS catalog_item_name, l.code AS location_code
    FROM v_reconciliation_errors e
    JOIN catalog_items ci ON ci.id = e.catalog_item_id
    LEFT JOIN locations l ON l.id = e.location_id
    ORDER BY ci.part_number, l.code
"""


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(db: DbSession, user: CurrentUser) -> Any:
    total_by_category = [
        dict(row._mapping) for row in (await db.execute(text(_CATEGORY_TOTALS_QUERY)))
    ]

    below_reorder = [
        dict(row._mapping)
        for row in (
            await db.execute(text(AVAILABILITY_QUERY), {"category": None, "below_reorder": True})
        )
    ]

    open_delivery_notes = (
        await db.execute(
            select(func.count()).select_from(DeliveryNote).where(DeliveryNote.is_closed.is_(False))
        )
    ).scalar_one()

    recent_movements = (
        (
            await db.execute(
                select(StockMovement)
                .order_by(StockMovement.occurred_at.desc())
                .limit(RECENT_MOVEMENTS_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    warranty_cutoff = date.today() + timedelta(days=WARRANTY_HORIZON_DAYS)
    expiring_warranties = (
        (
            await db.execute(
                select(StockUnit)
                .where(
                    StockUnit.warranty_end.is_not(None),
                    StockUnit.warranty_end <= warranty_cutoff,
                    StockUnit.status == UnitStatus.in_stock,
                )
                .order_by(StockUnit.warranty_end.asc())
                .limit(EXPIRING_WARRANTIES_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    reconciliation_error_rows: list[dict[str, Any]] = []
    if user.role == UserRole.admin:
        reconciliation_error_rows = [
            dict(row._mapping) for row in (await db.execute(text(_RECONCILIATION_QUERY)))
        ]

    return DashboardResponse(
        total_by_category=total_by_category,
        below_reorder=below_reorder,
        open_delivery_notes=open_delivery_notes,
        recent_movements=recent_movements,
        expiring_warranties=expiring_warranties,
        reconciliation_errors=len(reconciliation_error_rows),
        reconciliation_error_rows=reconciliation_error_rows,
    )
