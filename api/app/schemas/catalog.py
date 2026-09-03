import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.enums import LocationType
from app.schemas.common import OrmModel


class VendorCreate(BaseModel):
    code: str
    name: str
    notes: str | None = None


class VendorUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class VendorResponse(OrmModel):
    id: uuid.UUID
    code: str
    name: str
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryCreate(BaseModel):
    code: str
    name: str
    parent_id: uuid.UUID | None = None


class CategoryUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    parent_id: uuid.UUID | None = None


class CategoryResponse(OrmModel):
    id: uuid.UUID
    code: str
    name: str
    parent_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class SupplierCreate(BaseModel):
    name: str
    vat_number: str | None = None
    contact_ref: str | None = None
    notes: str | None = None


class SupplierUpdate(BaseModel):
    name: str | None = None
    vat_number: str | None = None
    contact_ref: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class SupplierResponse(OrmModel):
    id: uuid.UUID
    name: str
    vat_number: str | None
    contact_ref: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LocationCreate(BaseModel):
    # Facoltativo: se manca lo ricava il server dal nome («Scaffale A01» →
    # `SCAFFALE-A01`). Chi ha già una nomenclatura sua continua a scriverlo.
    code: str | None = None
    name: str
    type: LocationType
    parent_id: uuid.UUID | None = None
    address: str | None = None


class LocationUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    type: LocationType | None = None
    parent_id: uuid.UUID | None = None
    address: str | None = None
    is_active: bool | None = None


class LocationResponse(OrmModel):
    id: uuid.UUID
    code: str
    name: str
    type: LocationType
    parent_id: uuid.UUID | None
    address: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CatalogItemCreate(BaseModel):
    vendor_id: uuid.UUID
    category_id: uuid.UUID
    part_number: str
    name: str
    description: str | None = None
    is_serialized: bool = True
    uom: str = "PZ"
    reorder_point: int | None = None
    eol_date: date | None = None
    eos_date: date | None = None
    serial_pattern: str | None = None
    notes: str | None = None


class CatalogItemUpdate(BaseModel):
    vendor_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    part_number: str | None = None
    name: str | None = None
    description: str | None = None
    is_serialized: bool | None = None
    uom: str | None = None
    reorder_point: int | None = None
    eol_date: date | None = None
    eos_date: date | None = None
    serial_pattern: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class CatalogItemResponse(OrmModel):
    id: uuid.UUID
    vendor_id: uuid.UUID
    category_id: uuid.UUID
    part_number: str
    name: str
    description: str | None
    is_serialized: bool
    uom: str
    reorder_point: int | None
    eol_date: date | None
    eos_date: date | None
    serial_pattern: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
