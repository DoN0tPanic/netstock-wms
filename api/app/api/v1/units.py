import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import CurrentUser, DbSession, require_role
from app.exceptions import NotFoundError, ValidationAppError
from app.models.catalog import CatalogItem, Location, Vendor
from app.models.delivery import DeliveryNote, DeliveryNoteLine
from app.models.enums import ItemCondition, UnitStatus, UserRole
from app.models.movements import StockMovement
from app.models.stock import StockUnit
from app.models.users import User
from app.schemas.common import Page
from app.schemas.stock import (
    AttachDeliveryNoteRequest,
    StockMovementResponse,
    StockUnitResponse,
    StockUnitUpdate,
)
from app.services.audit import write_audit
from app.services.serials import MAC_PATTERN, normalize_mac, normalize_serial

router = APIRouter(prefix="/units", tags=["units"])


async def _enrich(db: AsyncSession, unit: StockUnit) -> StockUnit:
    catalog_row = (
        await db.execute(
            select(CatalogItem.part_number, CatalogItem.name, Vendor.code)
            .join(Vendor, Vendor.id == CatalogItem.vendor_id)
            .where(CatalogItem.id == unit.catalog_item_id)
        )
    ).first()
    if catalog_row:
        unit.part_number, unit.catalog_item_name, unit.vendor_code = catalog_row

    if unit.delivery_note_line_id is not None:
        unit.delivery_note_number = (
            await db.execute(
                select(DeliveryNote.number)
                .join(DeliveryNoteLine, DeliveryNoteLine.delivery_note_id == DeliveryNote.id)
                .where(DeliveryNoteLine.id == unit.delivery_note_line_id)
            )
        ).scalar_one_or_none()

    if unit.location_id is not None:
        unit.location_code = (
            await db.execute(select(Location.code).where(Location.id == unit.location_id))
        ).scalar_one_or_none()

    return unit


@router.get("", response_model=Page[StockUnitResponse])
async def list_units(
    db: DbSession,
    user: CurrentUser,
    q: str | None = None,
    item: uuid.UUID | None = None,
    status: UnitStatus | None = None,
    location: uuid.UUID | None = None,
    condition: ItemCondition | None = None,
    warranty_before: date | None = None,
    page: int = 1,
    page_size: int = 50,
) -> Any:
    page_size = min(page_size, 200)
    filters = []
    if q:
        normalized = normalize_serial(q)
        filters.append(
            StockUnit.serial_number.ilike(f"%{normalized}%")
            | StockUnit.mac_address.cast(String).ilike(f"%{q}%")
        )
    if item:
        filters.append(StockUnit.catalog_item_id == item)
    if status:
        filters.append(StockUnit.status == status)
    if location:
        filters.append(StockUnit.location_id == location)
    if condition:
        filters.append(StockUnit.condition == condition)
    if warranty_before:
        filters.append(StockUnit.warranty_end <= warranty_before)

    total = (
        await db.execute(select(func.count()).select_from(StockUnit).where(*filters))
    ).scalar_one()
    stmt = select(StockUnit).where(*filters).offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(stmt)).scalars().all()
    return Page(items=list(items), total=total, page=page, page_size=page_size)


@router.get("/by-serial/{serial}", response_model=StockUnitResponse)
async def get_unit_by_serial(serial: str, db: DbSession, user: CurrentUser) -> Any:
    normalized = normalize_serial(serial)
    result = await db.execute(
        select(StockUnit).where(func.upper(StockUnit.serial_number) == normalized)
    )
    unit = result.scalar_one_or_none()
    if unit is None:
        raise NotFoundError("Unità non trovata.", details={"serial_number": normalized})
    return unit


@router.get("/{unit_id}", response_model=StockUnitResponse)
async def get_unit(unit_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Any:
    unit = await db.get(StockUnit, unit_id)
    if unit is None:
        raise NotFoundError("Unità non trovata.", details={"id": str(unit_id)})
    return await _enrich(db, unit)


@router.get("/{unit_id}/movements", response_model=list[StockMovementResponse])
async def get_unit_movements(unit_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Any:
    result = await db.execute(
        select(StockMovement)
        .where(StockMovement.stock_unit_id == unit_id)
        .order_by(StockMovement.occurred_at.desc())
    )
    return result.scalars().all()


@router.patch("/{unit_id}", response_model=StockUnitResponse)
async def update_unit(
    unit_id: uuid.UUID,
    payload: StockUnitUpdate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    unit = await db.get(StockUnit, unit_id)
    if unit is None:
        raise NotFoundError("Unità non trovata.", details={"id": str(unit_id)})
    changes = payload.model_dump(exclude_unset=True)

    if "serial_number" in changes:
        serial = normalize_serial(changes["serial_number"])
        if not serial:
            raise ValidationAppError("Il seriale non può essere vuoto.")
        duplicate = await db.execute(
            select(StockUnit.id).where(
                StockUnit.catalog_item_id == unit.catalog_item_id,
                StockUnit.serial_number == serial,
                StockUnit.id != unit.id,
            )
        )
        if duplicate.scalar_one_or_none() is not None:
            raise ValidationAppError(
                f"Seriale già presente per questo articolo: {serial}",
                details={"serial_number": serial},
            )
        changes["serial_number"] = serial

    if "mac_address" in changes and changes["mac_address"]:
        mac = normalize_mac(changes["mac_address"])
        if not MAC_PATTERN.match(mac):
            raise ValidationAppError(f"Indirizzo MAC non valido: {changes['mac_address']}")
        changes["mac_address"] = mac

    for key, value in changes.items():
        setattr(unit, key, value)
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="unit.update",
        entity_type="stock_unit",
        entity_id=str(unit.id),
        details={"changed_fields": changes},
    )
    return await _enrich(db, unit)


@router.post("/{unit_id}/attach-delivery-note", response_model=StockUnitResponse)
async def attach_delivery_note(
    unit_id: uuid.UUID,
    payload: AttachDeliveryNoteRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    """Link a delivery note to a unit that was received without one — e.g.
    equipment that arrived with no paperwork and whose DDT surfaces later.

    Only fills in a missing association; a unit that already has one is left
    alone (correcting a wrong one goes through a rettifica, see the unit
    detail screen), since this must never rewrite what actually happened at
    receipt time.
    """
    unit = await db.get(StockUnit, unit_id)
    if unit is None:
        raise NotFoundError("Unità non trovata.", details={"id": str(unit_id)})
    if unit.delivery_note_line_id is not None:
        raise ValidationAppError(
            "Questa unità ha già una bolla associata: per correggerla usa una rettifica."
        )

    note = await db.get(DeliveryNote, payload.delivery_note_id)
    if note is None:
        raise NotFoundError(
            "Bolla non trovata.", details={"delivery_note_id": str(payload.delivery_note_id)}
        )

    line_result = await db.execute(
        select(DeliveryNoteLine)
        .where(
            DeliveryNoteLine.delivery_note_id == note.id,
            DeliveryNoteLine.catalog_item_id == unit.catalog_item_id,
        )
        .with_for_update()
    )
    line = line_result.scalars().first()
    if line is None:
        max_line = (
            await db.execute(
                select(func.coalesce(func.max(DeliveryNoteLine.line_number), 0)).where(
                    DeliveryNoteLine.delivery_note_id == note.id
                )
            )
        ).scalar_one()
        line = DeliveryNoteLine(
            delivery_note_id=note.id,
            line_number=max_line + 1,
            catalog_item_id=unit.catalog_item_id,
            qty_expected=1,
            qty_received=1,
            condition=unit.condition,
        )
        db.add(line)
        await db.flush()
    else:
        line.qty_received = line.qty_received + 1
        if line.qty_expected < line.qty_received:
            line.qty_expected = line.qty_received

    unit.delivery_note_line_id = line.id
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="unit.attach_delivery_note",
        entity_type="stock_unit",
        entity_id=str(unit.id),
        details={"delivery_note_id": str(note.id), "delivery_note_line_id": str(line.id)},
    )
    return await _enrich(db, unit)
