import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError, ValidationAppError
from app.models.enums import UnitStatus
from app.models.reservations import Reservation
from app.models.reservations import ReservationStatus as ResStatus
from app.models.stock import StockUnit
from app.models.users import User
from app.services import state_machine
from app.services.audit import write_audit


async def create_reservation(
    db: AsyncSession,
    *,
    performer: User,
    catalog_item_id: uuid.UUID,
    stock_unit_id: uuid.UUID | None,
    quantity: Decimal,
    location_id: uuid.UUID | None,
    reference: str,
    requested_by: str,
    expires_at: date | None,
    notes: str | None,
) -> Reservation:
    if stock_unit_id is not None:
        result = await db.execute(
            select(StockUnit).where(StockUnit.id == stock_unit_id).with_for_update()
        )
        unit = result.scalar_one_or_none()
        if unit is None:
            raise NotFoundError("Unità non trovata.", details={"unit_id": str(stock_unit_id)})
        unit.status = state_machine.reserve(unit.status)
        quantity = Decimal("1")

    reservation = Reservation(
        catalog_item_id=catalog_item_id,
        stock_unit_id=stock_unit_id,
        quantity=quantity,
        location_id=location_id,
        reference=reference,
        requested_by=requested_by,
        status=ResStatus.open,
        expires_at=expires_at,
        notes=notes,
        created_by=performer.id,
    )
    db.add(reservation)
    await db.flush()

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="reservation.create",
        entity_type="reservation",
        entity_id=str(reservation.id),
        details={"reference": reference, "quantity": float(quantity)},
    )
    return reservation


async def cancel_reservation(
    db: AsyncSession, *, performer: User, reservation_id: uuid.UUID
) -> Reservation:
    result = await db.execute(
        select(Reservation).where(Reservation.id == reservation_id).with_for_update()
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise NotFoundError(
            "Prenotazione non trovata.", details={"reservation_id": str(reservation_id)}
        )
    if reservation.status != ResStatus.open:
        raise ValidationAppError("Solo una prenotazione aperta può essere annullata.")

    if reservation.stock_unit_id is not None:
        unit_result = await db.execute(
            select(StockUnit).where(StockUnit.id == reservation.stock_unit_id).with_for_update()
        )
        unit = unit_result.scalar_one_or_none()
        if unit is not None and unit.status == UnitStatus.reserved:
            unit.status = state_machine.release_reservation(unit.status)

    reservation.status = ResStatus.cancelled
    await db.flush()

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="reservation.cancel",
        entity_type="reservation",
        entity_id=str(reservation.id),
        details={},
    )
    return reservation


async def fulfil_reservation(
    db: AsyncSession, *, performer: User, reservation_id: uuid.UUID, movement_id: uuid.UUID
) -> Reservation:
    result = await db.execute(
        select(Reservation).where(Reservation.id == reservation_id).with_for_update()
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise NotFoundError(
            "Prenotazione non trovata.", details={"reservation_id": str(reservation_id)}
        )
    if reservation.status != ResStatus.open:
        raise ValidationAppError("Solo una prenotazione aperta può essere evasa.")

    reservation.status = ResStatus.fulfilled
    reservation.fulfilled_movement_id = movement_id
    await db.flush()

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="reservation.fulfil",
        entity_type="reservation",
        entity_id=str(reservation.id),
        details={"movement_id": str(movement_id)},
    )
    return reservation


async def expire_reservations(db: AsyncSession, *, system_actor_username: str = "system") -> int:
    """Run by the daily job (§5.5, §6.5). Returns the number of reservations expired."""
    today = datetime.now(UTC).date()
    result = await db.execute(
        select(Reservation).where(
            Reservation.status == ResStatus.open,
            Reservation.expires_at.is_not(None),
            Reservation.expires_at < today,
        )
    )
    reservations = result.scalars().all()

    for reservation in reservations:
        reservation.status = ResStatus.expired
        if reservation.stock_unit_id is not None:
            unit_result = await db.execute(
                select(StockUnit).where(StockUnit.id == reservation.stock_unit_id)
            )
            unit = unit_result.scalar_one_or_none()
            if unit is not None and unit.status == UnitStatus.reserved:
                unit.status = UnitStatus.in_stock

        await write_audit(
            db,
            actor=None,
            actor_username=system_actor_username,
            action="reservation.expired",
            entity_type="reservation",
            entity_id=str(reservation.id),
            details={"reference": reservation.reference},
        )

    await db.flush()
    return len(reservations)
