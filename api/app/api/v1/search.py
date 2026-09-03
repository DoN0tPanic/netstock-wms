from typing import Any

from fastapi import APIRouter
from sqlalchemy import String, select

from app.deps import CurrentUser, DbSession
from app.models.catalog import CatalogItem, Location
from app.models.delivery import DeliveryNote
from app.models.stock import StockUnit
from app.schemas.search import SearchResponse, SearchResult

router = APIRouter(tags=["search"])

_PER_TYPE_LIMIT = 5


@router.get("/search", response_model=SearchResponse)
async def global_search(db: DbSession, user: CurrentUser, q: str) -> Any:
    query = q.strip()
    if not query or len(query) < 2:
        return {"results": []}

    results: list[SearchResult] = []

    unit_rows = (
        await db.execute(
            select(StockUnit)
            .where(
                StockUnit.serial_number.ilike(f"%{query}%")
                | StockUnit.mac_address.cast(String).ilike(f"%{query}%")
            )
            .limit(_PER_TYPE_LIMIT)
        )
    ).scalars().all()
    for unit in unit_rows:
        results.append(
            SearchResult(
                type="unit",
                id=str(unit.id),
                label=unit.serial_number,
                sublabel=unit.mac_address,
                path=f"/units/{unit.id}",
            )
        )

    item_rows = (
        await db.execute(
            select(CatalogItem)
            .where(
                CatalogItem.part_number.ilike(f"%{query}%")
                | CatalogItem.name.ilike(f"%{query}%")
            )
            .limit(_PER_TYPE_LIMIT)
        )
    ).scalars().all()
    for item in item_rows:
        results.append(
            SearchResult(
                type="catalog_item",
                id=str(item.id),
                label=item.part_number,
                sublabel=item.name,
                path=f"/stock?item={item.id}",
            )
        )

    note_rows = (
        await db.execute(
            select(DeliveryNote).where(DeliveryNote.number.ilike(f"%{query}%")).limit(_PER_TYPE_LIMIT)
        )
    ).scalars().all()
    for note in note_rows:
        results.append(
            SearchResult(
                type="delivery_note",
                id=str(note.id),
                label=note.number,
                sublabel=note.note_date.isoformat(),
                path=f"/delivery-notes/{note.id}",
            )
        )

    location_rows = (
        await db.execute(
            select(Location)
            .where(Location.code.ilike(f"%{query}%") | Location.name.ilike(f"%{query}%"))
            .limit(_PER_TYPE_LIMIT)
        )
    ).scalars().all()
    for location in location_rows:
        results.append(
            SearchResult(
                type="location",
                id=str(location.id),
                label=location.code,
                sublabel=location.name,
                path=f"/stock?location={location.id}",
            )
        )

    return {"results": results}
