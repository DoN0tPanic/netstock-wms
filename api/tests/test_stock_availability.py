"""Quanto si può prelevare da un'ubicazione è la sua giacenza.

Era «giacenza meno prenotato»; le prenotazioni sono state tolte dal prodotto
(migrazione 0010). Il vecchio calcolo sottraeva le prenotazioni di tutte le
ubicazioni dalla giacenza di una sola: questo test tiene fermo che
un'ubicazione risponda soltanto della merce che ha.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.enums import ItemCondition, MovementType
from app.models.movements import StockMovement
from app.models.users import User
from app.services import stock as stock_service


async def test_il_disponibile_e_la_giacenza_di_quell_ubicazione(app_db_session) -> None:
    db = app_db_session
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    prima, seconda = (await db.execute(select(Location).limit(2))).scalars().all()
    admin = (await db.execute(select(User).limit(1))).scalar_one()

    articolo = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"AVAIL-TEST-{uuid.uuid4().hex[:8]}",
        name="Articolo di test disponibilità",
        is_serialized=False,
    )
    db.add(articolo)
    await db.flush()
    for ubicazione, quanti in ((prima, "20"), (seconda, "7")):
        db.add(
            StockMovement(
                occurred_at=datetime.now(UTC),
                type=MovementType.receipt,
                catalog_item_id=articolo.id,
                quantity=Decimal(quanti),
                condition=ItemCondition.new,
                location_to_id=ubicazione.id,
                performed_by=admin.id,
            )
        )
    await db.flush()

    assert await stock_service.get_available(
        db, articolo.id, prima.id, ItemCondition.new
    ) == Decimal("20")
    assert await stock_service.get_available(
        db, articolo.id, seconda.id, ItemCondition.new
    ) == Decimal("7")
