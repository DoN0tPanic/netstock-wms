import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.enums import ItemCondition, MovementType, ReservationStatus
from app.models.movements import StockMovement
from app.models.reservations import Reservation
from app.models.users import User
from app.services import stock as stock_service


async def test_get_available_with_open_reservation(app_db_session) -> None:
    """Regression test: get_reserved() used to wrap the aggregate in
    sqlalchemy.cast() and pass that expression object straight into
    Decimal(), which raises `TypeError: conversion from Cast to Decimal is
    not supported` for every bulk (non-serialized) issue/transfer/adjust/
    scrap once a reservation existed for the item. This blocked every bulk
    quantity movement in practice.
    """
    db = app_db_session
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    location = (await db.execute(select(Location).limit(1))).scalar_one()
    admin = (await db.execute(select(User).limit(1))).scalar_one()

    item = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"AVAIL-TEST-{uuid.uuid4().hex[:8]}",
        name="Articolo di test disponibilità",
        is_serialized=False,
    )
    db.add(item)
    await db.flush()

    receipt = StockMovement(
        occurred_at=datetime.now(UTC),
        type=MovementType.receipt,
        catalog_item_id=item.id,
        quantity=Decimal("20"),
        condition=ItemCondition.new,
        location_to_id=location.id,
        performed_by=admin.id,
    )
    db.add(receipt)

    reservation = Reservation(
        catalog_item_id=item.id,
        quantity=Decimal("5"),
        reference="TEST-REF",
        requested_by="Test",
        status=ReservationStatus.open,
        created_by=admin.id,
    )
    db.add(reservation)
    await db.flush()

    available = await stock_service.get_available(db, item.id, location.id, ItemCondition.new)
    assert available == Decimal("15")
