import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import ItemCondition
from app.schemas.common import OrmModel


class DeliveryNoteLineCreate(BaseModel):
    catalog_item_id: uuid.UUID
    qty_expected: Decimal
    condition: ItemCondition = ItemCondition.new
    notes: str | None = None


class DeliveryNoteCreate(BaseModel):
    number: str
    note_date: date
    supplier_id: uuid.UUID
    po_number: str | None = None
    carrier: str | None = None
    tracking_number: str | None = None
    notes: str | None = None
    lines: list[DeliveryNoteLineCreate] = []


class DeliveryNoteUpdate(BaseModel):
    number: str | None = None
    note_date: date | None = None
    supplier_id: uuid.UUID | None = None
    po_number: str | None = None
    carrier: str | None = None
    tracking_number: str | None = None
    notes: str | None = None


class DeliveryNoteLineResponse(OrmModel):
    id: uuid.UUID
    delivery_note_id: uuid.UUID
    line_number: int
    catalog_item_id: uuid.UUID
    qty_expected: Decimal
    qty_received: Decimal
    condition: ItemCondition
    notes: str | None


class DeliveryNoteResponse(OrmModel):
    id: uuid.UUID
    number: str
    note_date: date
    supplier_id: uuid.UUID
    po_number: str | None
    carrier: str | None
    tracking_number: str | None
    received_at: datetime
    received_by: uuid.UUID
    is_closed: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DeliveryNoteDetailResponse(DeliveryNoteResponse):
    lines: list[DeliveryNoteLineResponse] = []


class SerialInputSchema(BaseModel):
    serial_number: str
    mac_address: str | None = None
    location_id: uuid.UUID | None = None  # overrides the request-level default for this piece


class ReceiveLineSchema(BaseModel):
    line_id: uuid.UUID
    condition: ItemCondition = ItemCondition.new
    serials: list[SerialInputSchema] = []
    quantity: Decimal | None = None


class ReceiveRequest(BaseModel):
    occurred_at: datetime | None = None
    location_id: uuid.UUID
    lines: list[ReceiveLineSchema]
    confirm_warnings: list[str] = []


class ReceiveResponse(BaseModel):
    created_unit_ids: list[uuid.UUID]
    movement_ids: list[uuid.UUID]
    delivery_note_closed: bool


class DeliveryNoteCloseRequest(BaseModel):
    reason: str
