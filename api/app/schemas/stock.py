import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import ItemCondition, MovementType, UnitStatus
from app.schemas.common import OrmModel


class StockUnitUpdate(BaseModel):
    serial_number: str | None = None
    mac_address: str | None = None
    notes: str | None = None
    warranty_end: date | None = None
    contract_ref: str | None = None


class AttachDeliveryNoteRequest(BaseModel):
    delivery_note_id: uuid.UUID


class FreeReceiveSerialSchema(BaseModel):
    serial_number: str
    mac_address: str | None = None
    location_id: uuid.UUID | None = None


class FreeReceiveLineSchema(BaseModel):
    catalog_item_id: uuid.UUID
    condition: ItemCondition = ItemCondition.new
    serials: list[FreeReceiveSerialSchema] = []
    quantity: Decimal | None = None


class FreeReceiveRequest(BaseModel):
    occurred_at: datetime | None = None
    location_id: uuid.UUID
    lines: list[FreeReceiveLineSchema]
    confirm_warnings: list[str] = []


class FreeReceiveResponse(BaseModel):
    created_unit_ids: list[uuid.UUID]
    movement_ids: list[uuid.UUID]


class StockUnitResponse(OrmModel):
    id: uuid.UUID
    catalog_item_id: uuid.UUID
    serial_number: str
    mac_address: str | None
    status: UnitStatus
    condition: ItemCondition
    location_id: uuid.UUID | None
    delivery_note_line_id: uuid.UUID | None
    purchase_date: date | None
    warranty_end: date | None
    contract_ref: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    # Denormalized for the unit detail view (model and delivery note are
    # deliberately read-only there — see `part_number`/`delivery_note_number`
    # below — so the frontend doesn't need extra round trips just to display
    # them). Set as plain attributes on the ORM instance by the route.
    part_number: str | None = None
    catalog_item_name: str | None = None
    vendor_code: str | None = None
    delivery_note_number: str | None = None
    location_code: str | None = None


class StockMovementResponse(OrmModel):
    id: uuid.UUID
    occurred_at: datetime
    type: MovementType
    catalog_item_id: uuid.UUID
    stock_unit_id: uuid.UUID | None
    quantity: Decimal
    condition: ItemCondition
    location_from_id: uuid.UUID | None
    location_to_id: uuid.UUID | None
    delivery_note_id: uuid.UUID | None
    reference: str | None
    assignee: str | None
    reason: str | None
    reverses_id: uuid.UUID | None
    performed_by: uuid.UUID
    notes: str | None
    created_at: datetime
    # Denormalized for the movements log, which is unreadable when every
    # column is a raw UUID. Set as plain attributes by the listing route;
    # absent elsewhere, so they fall back to None.
    part_number: str | None = None
    serial_number: str | None = None
    location_from_code: str | None = None
    location_to_code: str | None = None
    performed_by_username: str | None = None
    is_reversed: bool = False


class StockBalanceResponse(BaseModel):
    catalog_item_id: uuid.UUID
    part_number: str
    name: str
    vendor_code: str
    category_code: str
    is_serialized: bool
    reorder_point: int | None
    qty_on_hand: Decimal
    qty_reserved: Decimal
    qty_available: Decimal
    below_reorder_point: bool


class UnitLineRequest(BaseModel):
    unit_id: uuid.UUID


class BulkLineRequest(BaseModel):
    catalog_item_id: uuid.UUID
    quantity: Decimal
    condition: ItemCondition = ItemCondition.new


class IssueRequest(BaseModel):
    occurred_at: datetime | None = None
    location_from_id: uuid.UUID
    reference: str
    assignee: str | None = None
    items: list[UnitLineRequest | BulkLineRequest] = []
    reservation_id: uuid.UUID | None = None
    notes: str | None = None


class TransferRequest(BaseModel):
    occurred_at: datetime | None = None
    # Optional: a unit currently without a location (issued, lost, in RMA) has
    # no "from" to report — the ledger records that honestly as NULL ("da
    # esterno") rather than forcing a fake location.
    location_from_id: uuid.UUID | None = None
    location_to_id: uuid.UUID
    unit_ids: list[uuid.UUID] = []
    bulk_items: list[BulkLineRequest] = []
    notes: str | None = None


class ReturnRequest(BaseModel):
    occurred_at: datetime | None = None
    location_to_id: uuid.UUID
    reference: str
    unit_ids: list[uuid.UUID] = []
    bulk_items: list[BulkLineRequest] = []
    notes: str | None = None


class RmaOutRequest(BaseModel):
    occurred_at: datetime | None = None
    location_from_id: uuid.UUID
    location_to_id: uuid.UUID
    reference: str
    unit_ids: list[uuid.UUID]
    notes: str | None = None


class RmaInRequest(BaseModel):
    occurred_at: datetime | None = None
    location_from_id: uuid.UUID
    location_to_id: uuid.UUID
    reference: str
    unit_ids: list[uuid.UUID]
    notes: str | None = None


class AdjustRequest(BaseModel):
    occurred_at: datetime | None = None
    reason: str
    unit_id: uuid.UUID | None = None
    catalog_item_id: uuid.UUID | None = None
    quantity: Decimal | None = None
    condition: ItemCondition = ItemCondition.new
    location_from_id: uuid.UUID | None = None
    location_to_id: uuid.UUID | None = None
    allow_negative: bool = False
    notes: str | None = None


class ScrapRequest(BaseModel):
    occurred_at: datetime | None = None
    reason: str
    location_from_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    catalog_item_id: uuid.UUID | None = None
    quantity: Decimal | None = None
    condition: ItemCondition = ItemCondition.new
    notes: str | None = None


class ReverseRequest(BaseModel):
    reason: str
