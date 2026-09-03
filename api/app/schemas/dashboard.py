import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.stock import StockBalanceResponse, StockMovementResponse, StockUnitResponse


class CategoryTotal(BaseModel):
    category_code: str
    category_name: str
    quantity: Decimal


class ReconciliationErrorRow(BaseModel):
    catalog_item_id: uuid.UUID
    location_id: uuid.UUID | None
    qty_ledger: Decimal
    qty_projection: Decimal
    part_number: str | None = None
    catalog_item_name: str | None = None
    location_code: str | None = None


class DashboardResponse(BaseModel):
    total_by_category: list[CategoryTotal]
    below_reorder: list[StockBalanceResponse]
    open_delivery_notes: int
    recent_movements: list[StockMovementResponse]
    expiring_warranties: list[StockUnitResponse]
    reconciliation_errors: int
    reconciliation_error_rows: list[ReconciliationErrorRow]
