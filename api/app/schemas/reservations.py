import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import ReservationStatus
from app.schemas.common import OrmModel


class ReservationCreate(BaseModel):
    catalog_item_id: uuid.UUID
    stock_unit_id: uuid.UUID | None = None
    quantity: Decimal = Decimal("1")
    location_id: uuid.UUID | None = None
    reference: str
    requested_by: str
    expires_at: date | None = None
    notes: str | None = None


class ReservationFulfilRequest(BaseModel):
    movement_id: uuid.UUID


class ReservationResponse(OrmModel):
    id: uuid.UUID
    catalog_item_id: uuid.UUID
    stock_unit_id: uuid.UUID | None
    quantity: Decimal
    location_id: uuid.UUID | None
    reference: str
    requested_by: str
    status: ReservationStatus
    expires_at: date | None
    fulfilled_movement_id: uuid.UUID | None
    notes: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
