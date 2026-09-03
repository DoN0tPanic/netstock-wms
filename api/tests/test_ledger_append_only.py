import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models.catalog import CatalogItem, Vendor
from app.models.enums import ItemCondition, MovementType
from app.models.movements import StockMovement
from app.models.users import User


async def _seed_minimal_movement(session) -> uuid.UUID:
    """Creates one throwaway movement inside the test's own transaction so
    the append-only trigger has a row to fire against, without depending on
    unrelated data left over from manual testing or prior test runs.
    """
    from app.models.catalog import Category
    from app.models.catalog import Location as LocationModel

    vendor = (await session.execute(select(Vendor).limit(1))).scalar_one()
    category = (await session.execute(select(Category).limit(1))).scalar_one()
    location = (await session.execute(select(LocationModel).limit(1))).scalar_one()
    admin = (await session.execute(select(User).limit(1))).scalar_one()

    item = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"TEST-{uuid.uuid4().hex[:8]}",
        name="Articolo di test",
        is_serialized=False,
    )
    session.add(item)
    await session.flush()

    movement = StockMovement(
        occurred_at=datetime.now(UTC),
        type=MovementType.receipt,
        catalog_item_id=item.id,
        quantity=Decimal("1"),
        condition=ItemCondition.new,
        location_to_id=location.id,
        performed_by=admin.id,
    )
    session.add(movement)
    await session.flush()
    return movement.id


async def test_update_on_stock_movements_is_rejected_by_trigger(superuser_connection) -> None:
    vendor_id = (
        await superuser_connection.execute(text("SELECT id FROM vendors LIMIT 1"))
    ).scalar_one()
    category_id = (
        await superuser_connection.execute(text("SELECT id FROM categories LIMIT 1"))
    ).scalar_one()
    location_id = (
        await superuser_connection.execute(text("SELECT id FROM locations LIMIT 1"))
    ).scalar_one()
    admin_id = (
        await superuser_connection.execute(text("SELECT id FROM users LIMIT 1"))
    ).scalar_one()

    item_id = (
        await superuser_connection.execute(
            text(
                "INSERT INTO catalog_items (vendor_id, category_id, part_number, name, is_serialized) "
                "VALUES (:vendor_id, :category_id, :pn, 'Test', FALSE) RETURNING id"
            ),
            {
                "vendor_id": vendor_id,
                "category_id": category_id,
                "pn": f"TEST-{uuid.uuid4().hex[:8]}",
            },
        )
    ).scalar_one()

    movement_id = (
        await superuser_connection.execute(
            text(
                "INSERT INTO stock_movements "
                "(type, catalog_item_id, quantity, location_to_id, performed_by) "
                "VALUES ('receipt', :item_id, 1, :location_id, :admin_id) RETURNING id"
            ),
            {"item_id": item_id, "location_id": location_id, "admin_id": admin_id},
        )
    ).scalar_one()

    with pytest.raises(DBAPIError, match="append-only"):
        await superuser_connection.execute(
            text("UPDATE stock_movements SET reason = 'hack' WHERE id = :id"),
            {"id": movement_id},
        )


async def test_app_role_cannot_update_stock_movements(app_db_session) -> None:
    movement_id = await _seed_minimal_movement(app_db_session)

    with pytest.raises(DBAPIError):
        await app_db_session.execute(
            text("UPDATE stock_movements SET reason = 'hack' WHERE id = :id"),
            {"id": movement_id},
        )
