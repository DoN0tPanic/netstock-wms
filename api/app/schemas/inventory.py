import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

InventoryRowKind = Literal["unit", "bulk"]


class InventoryRow(BaseModel):
    kind: InventoryRowKind
    row_key: str  # stock_unit id for 'unit' rows; a synthesized composite key for 'bulk' rows
    catalog_item_id: uuid.UUID
    part_number: str
    name: str
    vendor_code: str
    category_code: str
    location_id: uuid.UUID | None
    location_code: str | None
    location_name: str | None = None
    condition: str
    serial_number: str | None = None
    mac_address: str | None = None
    status: str | None = None
    delivery_note_number: str | None = None
    warranty_end: date | None = None
    # Campi descrittivi dell'unità: non entrano nelle colonne predefinite
    # della tabella, ma si possono aggiungere a schermo e ci sono sempre
    # nell'esportazione. Per il materiale sfuso sono vuoti — sono proprietà
    # di un pezzo, e lo sfuso di pezzi non ne ha.
    purchase_date: date | None = None
    contract_ref: str | None = None
    notes: str | None = None
    quantity: Decimal | None = None
