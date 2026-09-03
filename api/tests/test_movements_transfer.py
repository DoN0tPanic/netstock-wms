import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.exceptions import ValidationAppError
from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.enums import ItemCondition, MovementType, UnitStatus
from app.models.movements import StockMovement
from app.models.stock import StockUnit
from app.models.users import User
from app.services.movements import BulkLine, UnitLine, reverse, scrap, transfer


async def _seed_item(db, is_serialized: bool = True) -> CatalogItem:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    item = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"XFER-{uuid.uuid4().hex[:8]}",
        name="Articolo di test trasferimento",
        is_serialized=is_serialized,
    )
    db.add(item)
    await db.flush()
    return item


async def _seed_unit(db, status: UnitStatus, location_id: uuid.UUID | None) -> StockUnit:
    item = await _seed_item(db)
    unit = StockUnit(
        catalog_item_id=item.id,
        serial_number=f"XFER{uuid.uuid4().hex[:8]}".upper(),
        status=status,
        condition=ItemCondition.new,
        location_id=location_id,
    )
    db.add(unit)
    await db.flush()
    return unit


async def test_transfer_brings_issued_unit_back_to_in_stock(app_db_session) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    location = (await db.execute(select(Location).limit(1))).scalar_one()
    unit = await _seed_unit(db, UnitStatus.issued, location_id=None)

    movements = await transfer(
        db,
        performer=admin,
        location_from_id=None,
        location_to_id=location.id,
        unit_lines=[UnitLine(unit_id=unit.id)],
        bulk_lines=[],
        notes=None,
        occurred_at=None,
    )

    await db.refresh(unit)
    assert unit.status == UnitStatus.in_stock
    assert unit.location_id == location.id
    assert movements[0].location_from_id is None


@pytest.mark.parametrize("status", [UnitStatus.in_rma, UnitStatus.lost, UnitStatus.scrapped])
async def test_transfer_brings_other_non_terminal_statuses_back_to_in_stock(
    app_db_session, status: UnitStatus
) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    location = (await db.execute(select(Location).limit(1))).scalar_one()
    unit = await _seed_unit(db, status, location_id=None)

    await transfer(
        db,
        performer=admin,
        location_from_id=None,
        location_to_id=location.id,
        unit_lines=[UnitLine(unit_id=unit.id)],
        bulk_lines=[],
        notes=None,
        occurred_at=None,
    )

    await db.refresh(unit)
    assert unit.status == UnitStatus.in_stock
    assert unit.location_id == location.id


async def test_transfer_accepts_every_unit_status(app_db_session) -> None:
    """No status may leave a unit stranded: relocating it is the universal fix.

    Guards the product rule that goods never leave the archive — a piece the
    operator cannot give a location to is a piece they cannot correct.
    """
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    locations = (await db.execute(select(Location).limit(2))).scalars().all()

    for status in UnitStatus:
        unit = await _seed_unit(db, status, location_id=locations[0].id)
        await transfer(
            db,
            performer=admin,
            location_from_id=locations[0].id,
            location_to_id=locations[1].id,
            unit_lines=[UnitLine(unit_id=unit.id)],
            bulk_lines=[],
            notes=None,
            occurred_at=None,
        )
        await db.refresh(unit)
        assert unit.status == UnitStatus.in_stock, f"stato {status.value} non recuperabile"
        assert unit.location_id == locations[1].id


async def test_transfer_bulk_requires_location_from(app_db_session) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    location = (await db.execute(select(Location).limit(1))).scalar_one()
    item = await _seed_item(db, is_serialized=False)

    with pytest.raises(ValidationAppError):
        await transfer(
            db,
            performer=admin,
            location_from_id=None,
            location_to_id=location.id,
            unit_lines=[],
            bulk_lines=[BulkLine(catalog_item_id=item.id, quantity=Decimal("1"))],
            notes=None,
            occurred_at=None,
        )


async def test_reverse_of_scrap_puts_the_unit_back_in_stock(app_db_session) -> None:
    """A rottamazione registered by mistake must be undoable with "Storna".

    Regression guard: reversing a scrap routes through an `adjustment`
    movement, and `scrapped` was missing from that transition map — the button
    returned 409 INVALID_TRANSITION instead of undoing anything.
    """
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    location = (await db.execute(select(Location).limit(1))).scalar_one()
    unit = await _seed_unit(db, UnitStatus.in_stock, location_id=location.id)

    scrap_movement = await scrap(
        db,
        performer=admin,
        reason="Rottamazione registrata per errore durante il test",
        location_from_id=location.id,
        unit_line=UnitLine(unit_id=unit.id),
        bulk_line=None,
        occurred_at=None,
        notes=None,
    )
    await db.refresh(unit)
    assert unit.status == UnitStatus.scrapped

    await reverse(
        db,
        performer=admin,
        movement_id=scrap_movement.id,
        reason="Storno della rottamazione registrata per errore",
    )

    await db.refresh(unit)
    assert unit.status == UnitStatus.in_stock
    assert unit.location_id == location.id


async def _reconciliation_error_count(db) -> int:
    from sqlalchemy import text

    return (await db.execute(text("SELECT count(*) FROM v_reconciliation_errors"))).scalar_one()


async def test_transfer_uses_the_unit_real_location_not_the_caller_value(app_db_session) -> None:
    """The ledger must stay aligned even if the caller passes a stale source.

    Regression guard for the anomalies reported on the dashboard: a transfer
    that subtracted stock from a location the piece had already left made
    `v_reconciliation_errors` non-empty, with no way for the operator to
    understand or clear it.
    """
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    locations = (await db.execute(select(Location).limit(3))).scalars().all()
    a, b, c = locations[0], locations[1], locations[2]
    before = await _reconciliation_error_count(db)

    unit = await _seed_unit(db, UnitStatus.in_stock, location_id=a.id)
    # Seed the ledger so projection and ledger start in agreement.
    db.add(
        StockMovement(
            occurred_at=datetime.now(UTC),
            type=MovementType.receipt,
            catalog_item_id=unit.catalog_item_id,
            stock_unit_id=unit.id,
            quantity=Decimal("1"),
            condition=unit.condition,
            location_from_id=None,
            location_to_id=a.id,
            performed_by=admin.id,
        )
    )
    await db.flush()

    await transfer(
        db, performer=admin, location_from_id=a.id, location_to_id=b.id,
        unit_lines=[UnitLine(unit_id=unit.id)], bulk_lines=[], notes=None, occurred_at=None,
    )
    # Deliberately lie about the source: the piece is at B, not A.
    await transfer(
        db, performer=admin, location_from_id=a.id, location_to_id=c.id,
        unit_lines=[UnitLine(unit_id=unit.id)], bulk_lines=[], notes=None, occurred_at=None,
    )

    await db.refresh(unit)
    assert unit.location_id == c.id
    assert await _reconciliation_error_count(db) == before, "il registro si è disallineato"


async def test_transfer_to_the_same_location_is_rejected(app_db_session) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    location = (await db.execute(select(Location).limit(1))).scalar_one()
    unit = await _seed_unit(db, UnitStatus.in_stock, location_id=location.id)

    with pytest.raises(ValidationAppError):
        await transfer(
            db, performer=admin, location_from_id=location.id, location_to_id=location.id,
            unit_lines=[UnitLine(unit_id=unit.id)], bulk_lines=[], notes=None, occurred_at=None,
        )
