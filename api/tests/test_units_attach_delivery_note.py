import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.api.v1.units import attach_delivery_note
from app.exceptions import ValidationAppError
from app.models.catalog import CatalogItem, Category, Location, Supplier, Vendor
from app.models.delivery import DeliveryNote, DeliveryNoteLine
from app.models.enums import ItemCondition
from app.models.users import User
from app.schemas.stock import AttachDeliveryNoteRequest
from app.services.receiving import FreeReceiveLine, SerialInput, receive_free_stock


async def _first_supplier_id(db) -> uuid.UUID:
    result = await db.execute(select(Supplier).limit(1))
    supplier = result.scalar_one_or_none()
    if supplier is None:
        supplier = Supplier(name=f"Test Supplier {uuid.uuid4().hex[:6]}")
        db.add(supplier)
        await db.flush()
    return supplier.id


async def _new_delivery_note(db, admin) -> DeliveryNote:
    note = DeliveryNote(
        number=f"ATT-DDT-{uuid.uuid4().hex[:6]}",
        note_date=date.today(),
        supplier_id=await _first_supplier_id(db),
        received_by=admin.id,
    )
    db.add(note)
    await db.flush()
    return note


async def _receive_free_serials(db, admin, item_id, *serial_numbers) -> list[uuid.UUID]:
    location = (await db.execute(select(Location).limit(1))).scalar_one()
    result = await receive_free_stock(
        db,
        performer=admin,
        location_id=location.id,
        lines=[
            FreeReceiveLine(
                catalog_item_id=item_id,
                condition=ItemCondition.new,
                serials=[SerialInput(serial_number=s) for s in serial_numbers],
            )
        ],
        confirm_warnings={"format_mismatch"},
        occurred_at=None,
    )
    return result.created_unit_ids


async def _new_item(db) -> CatalogItem:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    item = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"ATTACH-{uuid.uuid4().hex[:8]}",
        name="Articolo di test collegamento bolla",
        is_serialized=True,
    )
    db.add(item)
    await db.flush()
    return item


async def test_attach_delivery_note_fills_missing_provenance(app_db_session) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    item = await _new_item(db)
    unique = uuid.uuid4().hex[:6]
    (unit_id,) = await _receive_free_serials(db, admin, item.id, f"ATT{unique}")
    note = await _new_delivery_note(db, admin)

    updated = await attach_delivery_note(
        unit_id, AttachDeliveryNoteRequest(delivery_note_id=note.id), db, admin
    )

    assert updated.delivery_note_number == note.number
    line = (
        await db.execute(
            select(DeliveryNoteLine).where(DeliveryNoteLine.delivery_note_id == note.id)
        )
    ).scalar_one()
    assert line.catalog_item_id == item.id
    assert line.qty_received == 1
    assert line.qty_expected == 1


async def test_attach_delivery_note_rejects_when_already_set(app_db_session) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    item = await _new_item(db)
    unique = uuid.uuid4().hex[:6]
    (unit_id,) = await _receive_free_serials(db, admin, item.id, f"ATT{unique}")
    note1 = await _new_delivery_note(db, admin)
    note2 = await _new_delivery_note(db, admin)

    await attach_delivery_note(
        unit_id, AttachDeliveryNoteRequest(delivery_note_id=note1.id), db, admin
    )

    with pytest.raises(ValidationAppError):
        await attach_delivery_note(
            unit_id, AttachDeliveryNoteRequest(delivery_note_id=note2.id), db, admin
        )


async def test_attach_delivery_note_reuses_line_and_bumps_expected(app_db_session) -> None:
    db = app_db_session
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    item = await _new_item(db)
    unique = uuid.uuid4().hex[:6]
    unit_a_id, unit_b_id = await _receive_free_serials(
        db, admin, item.id, f"ATTA{unique}", f"ATTB{unique}"
    )
    note = await _new_delivery_note(db, admin)

    await attach_delivery_note(
        unit_a_id, AttachDeliveryNoteRequest(delivery_note_id=note.id), db, admin
    )
    await attach_delivery_note(
        unit_b_id, AttachDeliveryNoteRequest(delivery_note_id=note.id), db, admin
    )

    lines = (
        await db.execute(
            select(DeliveryNoteLine).where(DeliveryNoteLine.delivery_note_id == note.id)
        )
    ).scalars().all()
    assert len(lines) == 1
    assert lines[0].qty_received == 2
    assert lines[0].qty_expected == 2
