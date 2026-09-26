import uuid
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ItemCondition
from app.models.movements import StockMovement


async def lock_item_location(
    db: AsyncSession, catalog_item_id: uuid.UUID, location_id: uuid.UUID | None
) -> None:
    """Serializes concurrent stock checks for one (item, location) pair.

    A view like v_stock_balance has no row to lock with SELECT ... FOR
    UPDATE, so we use a transaction-scoped advisory lock keyed on the pair
    (§5.1 point 4: "riga di lock dedicata"). Released automatically at
    transaction end.
    """
    key = f"{catalog_item_id}:{location_id or 'external'}"
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})


async def get_on_hand(
    db: AsyncSession,
    catalog_item_id: uuid.UUID,
    location_id: uuid.UUID | None,
    condition: ItemCondition,
) -> Decimal:
    inbound = select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
        StockMovement.catalog_item_id == catalog_item_id,
        StockMovement.location_to_id == location_id,
        StockMovement.condition == condition,
    )
    outbound = select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
        StockMovement.catalog_item_id == catalog_item_id,
        StockMovement.location_from_id == location_id,
        StockMovement.condition == condition,
    )
    inbound_total = (await db.execute(inbound)).scalar_one()
    outbound_total = (await db.execute(outbound)).scalar_one()
    return Decimal(inbound_total) - Decimal(outbound_total)


async def get_available(
    db: AsyncSession,
    catalog_item_id: uuid.UUID,
    location_id: uuid.UUID | None,
    condition: ItemCondition,
) -> Decimal:
    """Quanto si può prelevare da un'ubicazione: la sua giacenza.

    Era «giacenza meno prenotato», con le prenotazioni tolte dal prodotto
    (migrazione 0010). Il vecchio calcolo, per inciso, sottraeva le
    prenotazioni di tutte le ubicazioni dalla giacenza di una sola: una
    prenotazione a Roma poteva bloccare uno scarico a Milano.
    """
    return await get_on_hand(db, catalog_item_id, location_id, condition)
