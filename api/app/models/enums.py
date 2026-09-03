import enum

from sqlalchemy import Enum as SAEnum


class UserRole(str, enum.Enum):
    viewer = "viewer"
    operator = "operator"
    admin = "admin"


class LocationType(str, enum.Enum):
    warehouse = "warehouse"
    shelf = "shelf"
    box = "box"
    remote_site = "remote_site"
    transit = "transit"


class ItemCondition(str, enum.Enum):
    new = "new"
    refurbished = "refurbished"
    used = "used"
    faulty = "faulty"


class UnitStatus(str, enum.Enum):
    in_stock = "in_stock"
    reserved = "reserved"
    issued = "issued"
    in_rma = "in_rma"
    scrapped = "scrapped"
    lost = "lost"


class MovementType(str, enum.Enum):
    receipt = "receipt"
    issue = "issue"
    transfer = "transfer"
    return_ = "return"
    rma_out = "rma_out"
    rma_in = "rma_in"
    adjustment = "adjustment"
    scrap = "scrap"


class ReservationStatus(str, enum.Enum):
    open = "open"
    fulfilled = "fulfilled"
    cancelled = "cancelled"
    expired = "expired"


class TemplateDocType(str, enum.Enum):
    device_label = "device_label"
    box_label = "box_label"
    delivery_note = "delivery_note"
    packing_list = "packing_list"


def _values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


user_role_enum = SAEnum(
    UserRole, name="user_role", create_type=False, values_callable=_values
)
location_type_enum = SAEnum(
    LocationType, name="location_type", create_type=False, values_callable=_values
)
item_condition_enum = SAEnum(
    ItemCondition, name="item_condition", create_type=False, values_callable=_values
)
unit_status_enum = SAEnum(
    UnitStatus, name="unit_status", create_type=False, values_callable=_values
)
movement_type_enum = SAEnum(
    MovementType, name="movement_type", create_type=False, values_callable=_values
)
reservation_status_enum = SAEnum(
    ReservationStatus, name="reservation_status", create_type=False, values_callable=_values
)
template_doc_type_enum = SAEnum(
    TemplateDocType, name="template_doc_type", create_type=False, values_callable=_values
)
