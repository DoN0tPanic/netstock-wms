import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.api.v1.inventory import list_inventory
from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.enums import ItemCondition, MovementType, UnitStatus, UserRole
from app.models.movements import StockMovement
from app.models.stock import StockUnit
from app.models.users import User


@dataclass
class _FakeUser:
    role: UserRole


async def _seed_unit_and_bulk(db) -> tuple[str, str, uuid.UUID]:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    location = (await db.execute(select(Location).limit(1))).scalar_one()
    admin = (await db.execute(select(User).limit(1))).scalar_one()

    unique = uuid.uuid4().hex[:8]
    serial_item = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"INV-SER-{unique}",
        name="Articolo serializzato di test inventario",
        is_serialized=True,
    )
    bulk_item = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"INV-BULK-{unique}",
        name="Articolo sfuso di test inventario",
        is_serialized=False,
    )
    db.add_all([serial_item, bulk_item])
    await db.flush()

    serial_number = f"INVSN{unique.upper()}"
    unit = StockUnit(
        catalog_item_id=serial_item.id,
        serial_number=serial_number,
        status=UnitStatus.in_stock,
        condition=ItemCondition.new,
        location_id=location.id,
    )
    db.add(unit)

    receipt = StockMovement(
        occurred_at=datetime.now(UTC),
        type=MovementType.receipt,
        catalog_item_id=bulk_item.id,
        quantity=Decimal("10"),
        condition=ItemCondition.new,
        location_to_id=location.id,
        performed_by=admin.id,
    )
    db.add(receipt)
    await db.flush()

    return serial_number, bulk_item.part_number, location.id


async def test_inventory_includes_both_unit_and_bulk_rows(app_db_session) -> None:
    serial_number, bulk_part_number, _location_id = await _seed_unit_and_bulk(app_db_session)

    result = await list_inventory(
        db=app_db_session,
        user=_FakeUser(role=UserRole.viewer),
        q=serial_number,
        page=1,
        page_size=50,
    )
    assert result.total == 1
    assert result.items[0]["kind"] == "unit"
    assert result.items[0]["serial_number"] == serial_number
    assert result.items[0]["row_key"] is not None

    result_bulk = await list_inventory(
        db=app_db_session,
        user=_FakeUser(role=UserRole.viewer),
        q=bulk_part_number,
        page=1,
        page_size=50,
    )
    assert result_bulk.total == 1
    assert result_bulk.items[0]["kind"] == "bulk"
    assert result_bulk.items[0]["serial_number"] is None
    assert Decimal(result_bulk.items[0]["quantity"]) == Decimal("10")


async def test_inventory_filter_by_location(app_db_session) -> None:
    serial_number, _bulk_part_number, location_id = await _seed_unit_and_bulk(app_db_session)

    other_location = (
        await app_db_session.execute(select(Location).where(Location.id != location_id).limit(1))
    ).scalar_one()

    matching = await list_inventory(
        db=app_db_session,
        user=_FakeUser(role=UserRole.viewer),
        q=serial_number,
        location=location_id,
    )
    assert matching.total == 1

    non_matching = await list_inventory(
        db=app_db_session,
        user=_FakeUser(role=UserRole.viewer),
        q=serial_number,
        location=other_location.id,
    )
    assert non_matching.total == 0
