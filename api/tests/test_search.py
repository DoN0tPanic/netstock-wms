import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.api.v1.search import global_search
from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.enums import UnitStatus, UserRole
from app.models.stock import StockUnit


@dataclass
class _FakeUser:
    role: UserRole


async def test_search_finds_unit_by_serial(app_db_session) -> None:
    vendor = (await app_db_session.execute(select(Vendor).limit(1))).scalar_one()
    category = (await app_db_session.execute(select(Category).limit(1))).scalar_one()
    location = (await app_db_session.execute(select(Location).limit(1))).scalar_one()

    unique = uuid.uuid4().hex[:8]
    item = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"SEARCH-{unique}",
        name="Articolo di test ricerca",
        is_serialized=True,
    )
    app_db_session.add(item)
    await app_db_session.flush()

    serial_number = f"SEARCHSN{unique.upper()}"
    unit = StockUnit(
        catalog_item_id=item.id,
        serial_number=serial_number,
        status=UnitStatus.in_stock,
        location_id=location.id,
    )
    app_db_session.add(unit)
    await app_db_session.flush()

    # `unique` is a substring of both the serial (SEARCHSN{unique}) and the
    # part number (SEARCH-{unique}), so a single query should surface both.
    result = await global_search(db=app_db_session, user=_FakeUser(role=UserRole.viewer), q=unique)
    types_found = {r.type for r in result["results"]}
    assert "unit" in types_found
    assert "catalog_item" in types_found
    unit_result = next(r for r in result["results"] if r.type == "unit")
    assert unit_result.label == serial_number
    assert unit_result.path == f"/units/{unit.id}"


async def test_search_short_query_returns_empty(app_db_session) -> None:
    result = await global_search(db=app_db_session, user=_FakeUser(role=UserRole.viewer), q="a")
    assert result == {"results": []}
