import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.exceptions import ValidationAppError
from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.delivery import DeliveryNote, DeliveryNoteLine
from app.models.enums import ItemCondition
from app.models.movements import StockMovement
from app.models.stock import StockUnit
from app.models.users import User
from app.services.receiving import (
    FreeReceiveLine,
    ReceiveLine,
    SerialInput,
    receive_delivery_note,
    receive_free_stock,
)


async def _seed_receivable_line(db) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Returns (delivery_note_id, line_id, default_location_id, override_location_id)."""
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    locations = (await db.execute(select(Location).limit(2))).scalars().all()
    admin = (await db.execute(select(User).limit(1))).scalar_one()

    unique = uuid.uuid4().hex[:8]
    item = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"RECV-TEST-{unique}",
        name="Articolo di test ricezione",
        is_serialized=True,
    )
    db.add(item)
    await db.flush()

    note = DeliveryNote(
        number=f"RECV-DDT-{unique}",
        note_date=date.today(),
        supplier_id=(await _first_supplier_id(db)),
        received_by=admin.id,
    )
    db.add(note)
    await db.flush()

    line = DeliveryNoteLine(
        delivery_note_id=note.id,
        line_number=1,
        catalog_item_id=item.id,
        qty_expected=3,
        condition=ItemCondition.new,
    )
    db.add(line)
    await db.flush()

    return note.id, line.id, locations[0].id, locations[1].id


async def _first_supplier_id(db) -> uuid.UUID:
    from app.models.catalog import Supplier

    result = await db.execute(select(Supplier).limit(1))
    supplier = result.scalar_one_or_none()
    if supplier is None:
        supplier = Supplier(name=f"Test Supplier {uuid.uuid4().hex[:6]}")
        db.add(supplier)
        await db.flush()
    return supplier.id


async def test_receive_applies_default_location_when_serial_has_none(app_db_session) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    note_id, line_id, default_location, _override_location = await _seed_receivable_line(db)

    unique = uuid.uuid4().hex[:6]
    result = await receive_delivery_note(
        db,
        performer=admin,
        delivery_note_id=note_id,
        location_id=default_location,
        lines=[
            ReceiveLine(
                line_id=line_id,
                condition=ItemCondition.new,
                serials=[SerialInput(serial_number=f"RECVA{unique}")],
            )
        ],
        confirm_warnings={"format_mismatch"},
        occurred_at=None,
    )

    unit = (
        await db.execute(select(StockUnit).where(StockUnit.id == result.created_unit_ids[0]))
    ).scalar_one()
    assert unit.location_id == default_location


async def test_receive_per_serial_location_overrides_default(app_db_session) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    note_id, line_id, default_location, override_location = await _seed_receivable_line(db)

    unique = uuid.uuid4().hex[:6]
    result = await receive_delivery_note(
        db,
        performer=admin,
        delivery_note_id=note_id,
        location_id=default_location,
        lines=[
            ReceiveLine(
                line_id=line_id,
                condition=ItemCondition.new,
                serials=[
                    SerialInput(serial_number=f"RECVB{unique}"),
                    SerialInput(
                        serial_number=f"RECVC{unique}", location_id=override_location
                    ),
                ],
            )
        ],
        confirm_warnings={"format_mismatch"},
        occurred_at=None,
    )

    units = (
        await db.execute(
            select(StockUnit).where(StockUnit.id.in_(result.created_unit_ids))
        )
    ).scalars().all()
    # normalize_serial() uppercases everything before storage.
    by_serial = {u.serial_number: u for u in units}

    assert by_serial[f"RECVB{unique}".upper()].location_id == default_location
    assert by_serial[f"RECVC{unique}".upper()].location_id == override_location


async def test_receive_free_stock_creates_serialized_unit_without_delivery_note(
    app_db_session,
) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    location = (await db.execute(select(Location).limit(1))).scalar_one()

    unique = uuid.uuid4().hex[:8]
    item = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"FREE-TEST-{unique}",
        name="Articolo senza bolla",
        is_serialized=True,
    )
    db.add(item)
    await db.flush()

    result = await receive_free_stock(
        db,
        performer=admin,
        location_id=location.id,
        lines=[
            FreeReceiveLine(
                catalog_item_id=item.id,
                condition=ItemCondition.new,
                serials=[SerialInput(serial_number=f"FREEA{unique}")],
            )
        ],
        confirm_warnings={"format_mismatch"},
        occurred_at=None,
    )

    assert len(result.created_unit_ids) == 1
    unit = (
        await db.execute(select(StockUnit).where(StockUnit.id == result.created_unit_ids[0]))
    ).scalar_one()
    assert unit.location_id == location.id
    assert unit.delivery_note_line_id is None

    movement = (
        await db.execute(select(StockMovement).where(StockMovement.id == result.movement_ids[0]))
    ).scalar_one()
    assert movement.delivery_note_id is None
    assert movement.stock_unit_id == unit.id


async def test_receive_free_stock_bulk_item_without_delivery_note(app_db_session) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    location = (await db.execute(select(Location).limit(1))).scalar_one()

    unique = uuid.uuid4().hex[:8]
    item = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"FREE-BULK-{unique}",
        name="Patch cord senza bolla",
        is_serialized=False,
    )
    db.add(item)
    await db.flush()

    result = await receive_free_stock(
        db,
        performer=admin,
        location_id=location.id,
        lines=[
            FreeReceiveLine(
                catalog_item_id=item.id, condition=ItemCondition.new, quantity=Decimal("5")
            )
        ],
        confirm_warnings=set(),
        occurred_at=None,
    )

    assert result.created_unit_ids == []
    assert len(result.movement_ids) == 1
    movement = (
        await db.execute(select(StockMovement).where(StockMovement.id == result.movement_ids[0]))
    ).scalar_one()
    assert movement.delivery_note_id is None
    assert movement.quantity == Decimal("5")
    assert movement.location_to_id == location.id


async def test_un_serializzato_senza_seriali_e_una_riga_incompleta(app_db_session) -> None:
    """Zero seriali su un articolo serializzato non è una ricezione da zero pezzi.

    Il piano proseguiva con `quantity=None` e finiva contro il vincolo NOT
    NULL della colonna: chi chiamava riceveva un 500 invece di sapere cosa
    mancava. Trovato provando la correzione sulla data, con un payload che
    per sbaglio mandava una quantità su un articolo con i seriali.
    """
    admin = (await app_db_session.execute(select(User).limit(1))).scalar_one()
    ubicazione = (await app_db_session.execute(select(Location).limit(1))).scalar_one()
    modello = (await app_db_session.execute(select(CatalogItem).limit(1))).scalar_one()
    articolo = CatalogItem(
        vendor_id=modello.vendor_id,
        category_id=modello.category_id,
        part_number=f"SER-VUOTO-{uuid.uuid4().hex[:6].upper()}",
        name="Articolo serializzato senza pezzi",
        is_serialized=True,
    )
    app_db_session.add(articolo)
    await app_db_session.flush()

    with pytest.raises(ValidationAppError) as rifiuto:
        await receive_free_stock(
            app_db_session,
            performer=admin,
            location_id=ubicazione.id,
            lines=[
                FreeReceiveLine(
                    catalog_item_id=articolo.id,
                    condition=ItemCondition.new,
                    serials=[],
                    quantity=Decimal("1"),
                )
            ],
            confirm_warnings=set(),
            occurred_at=None,
        )
    assert "almeno un numero seriale" in rifiuto.value.message
