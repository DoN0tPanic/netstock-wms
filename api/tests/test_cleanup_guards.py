"""Guards around removing things created by mistake.

Deleting is the operation an operator reaches for after a typo, so each path
has to be exact about what it will and will not take away: never something a
movement already refers to.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.api.v1.delivery_notes import delete_delivery_note
from app.api.v1.registries import _location_is_empty
from app.exceptions import ValidationAppError
from app.models.catalog import CatalogItem, Category, Location, Supplier, Vendor
from app.models.delivery import DeliveryNote, DeliveryNoteLine
from app.models.enums import ItemCondition, UnitStatus
from app.models.stock import StockUnit
from app.models.users import User


async def _supplier_id(db) -> uuid.UUID:
    supplier = (await db.execute(select(Supplier).limit(1))).scalar_one_or_none()
    if supplier is None:
        supplier = Supplier(name=f"Fornitore {uuid.uuid4().hex[:6]}")
        db.add(supplier)
        await db.flush()
    return supplier.id


async def _new_note(db, admin) -> DeliveryNote:
    note = DeliveryNote(
        number=f"DEL-{uuid.uuid4().hex[:6]}",
        note_date=date.today(),
        supplier_id=await _supplier_id(db),
        received_by=admin.id,
    )
    db.add(note)
    await db.flush()
    return note


async def _new_item(db) -> CatalogItem:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    item = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"DEL-{uuid.uuid4().hex[:8]}",
        name="Articolo per test eliminazione",
        is_serialized=True,
    )
    db.add(item)
    await db.flush()
    return item


async def test_empty_delivery_note_can_be_deleted(app_db_session) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    note = await _new_note(db, admin)
    note_id = note.id

    await delete_delivery_note(note_id, db, admin)

    assert (await db.get(DeliveryNote, note_id)) is None


async def test_delivery_note_with_received_goods_cannot_be_deleted(app_db_session) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    note = await _new_note(db, admin)
    item = await _new_item(db)
    db.add(
        DeliveryNoteLine(
            delivery_note_id=note.id,
            line_number=1,
            catalog_item_id=item.id,
            qty_expected=1,
            qty_received=1,
            condition=ItemCondition.new,
        )
    )
    await db.flush()

    with pytest.raises(ValidationAppError):
        await delete_delivery_note(note.id, db, admin)

    assert (await db.get(DeliveryNote, note.id)) is not None


async def test_location_holding_goods_cannot_be_deactivated(app_db_session) -> None:
    db = app_db_session
    location = (await db.execute(select(Location).limit(1))).scalar_one()
    item = await _new_item(db)
    db.add(
        StockUnit(
            catalog_item_id=item.id,
            serial_number=f"DEL{uuid.uuid4().hex[:8]}".upper(),
            status=UnitStatus.in_stock,
            condition=ItemCondition.new,
            location_id=location.id,
        )
    )
    await db.flush()

    with pytest.raises(ValidationAppError):
        await _location_is_empty(db, location)


async def test_empty_location_can_be_deactivated(app_db_session) -> None:
    db = app_db_session
    location = Location(
        code=f"DEL-{uuid.uuid4().hex[:6]}".upper(), name="Ubicazione vuota", type="shelf"
    )
    db.add(location)
    await db.flush()

    await _location_is_empty(db, location)  # must not raise


async def test_unused_location_can_be_deleted(app_db_session) -> None:
    """The typo you notice a minute after saving must be removable."""
    from app.api.v1.registries import locations_router

    delete_location = next(
        route.endpoint for route in locations_router.routes if route.name == "delete_item"
    )
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    location = Location(
        code=f"DELME-{uuid.uuid4().hex[:6]}".upper(), name="Da eliminare", type="shelf"
    )
    db.add(location)
    await db.flush()
    location_id = location.id

    await delete_location(location_id, db, admin)

    assert (await db.get(Location, location_id)) is None


async def test_location_in_use_cannot_be_deleted(app_db_session) -> None:
    """A location a piece still points at must survive, with an explanation."""
    from app.api.v1.registries import locations_router

    delete_location = next(
        route.endpoint for route in locations_router.routes if route.name == "delete_item"
    )
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    location = Location(
        code=f"INUSE-{uuid.uuid4().hex[:6]}".upper(), name="In uso", type="shelf"
    )
    db.add(location)
    await db.flush()
    item = await _new_item(db)
    db.add(
        StockUnit(
            catalog_item_id=item.id,
            serial_number=f"USE{uuid.uuid4().hex[:8]}".upper(),
            status=UnitStatus.in_stock,
            condition=ItemCondition.new,
            location_id=location.id,
        )
    )
    await db.flush()

    with pytest.raises(ValidationAppError):
        await delete_location(location.id, db, admin)
