import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    AlreadyReversedError,
    InsufficientStockError,
    NotFoundError,
    ValidationAppError,
)
from app.models.enums import ItemCondition, MovementType
from app.models.movements import StockMovement
from app.models.stock import StockUnit
from app.models.users import User
from app.services import stock as stock_service
from app.services.audit import write_audit
from app.services.state_machine import apply_movement_transition

MIN_REASON_LENGTH = 10


@dataclass
class UnitLine:
    unit_id: uuid.UUID


@dataclass
class BulkLine:
    catalog_item_id: uuid.UUID
    quantity: Decimal
    condition: ItemCondition = ItemCondition.new


def _validate_reason(movement_type: MovementType, reason: str | None) -> None:
    if movement_type in (MovementType.adjustment, MovementType.scrap) and (
        not reason or len(reason.strip()) < MIN_REASON_LENGTH
    ):
        raise ValidationAppError(
            f"Il campo 'reason' è obbligatorio (minimo {MIN_REASON_LENGTH} caratteri) "
            "per rettifiche e rottamazioni.",
        )


# Quanto può essere avanti l'orologio di chi chiama, prima che la data smetta
# di essere un errore di sincronizzazione e diventi una data sbagliata.
#
# Il divieto di datare un movimento nel futuro (§6.6, punto 6) esiste per
# impedire registrazioni senza senso, non per litigare con un PC avanti di tre
# secondi. Senza tolleranza succedeva questo: da un browser leggermente
# sfasato, «Registra ricezione» falliva con «La data di ricezione non può
# essere nel futuro» — un messaggio che parla di date mentre il problema è un
# orologio, e che non lascia nessuna via d'uscita a chi lo legge. Tre secondi
# bastavano a bloccare l'intera registrazione.
TOLLERANZA_OROLOGIO = timedelta(minutes=5)


def validate_occurred_at(occurred_at: datetime | None, *, cosa: str = "del movimento") -> datetime:
    """La data di un movimento, normalizzata all'orologio del server.

    Il server è l'unico orologio di cui questo sistema può rispondere, quindi
    è quello che decide: entro la tolleranza una data «nel futuro» viene
    riportata ad adesso invece di essere rifiutata. Nel registro non resta un
    movimento datato domani — che a chi lo rileggesse sembrerebbe un dato
    corrotto, e che una query «fino a oggi» non troverebbe.
    """
    now = datetime.now(UTC)
    if occurred_at is None:
        return now
    if occurred_at > now + TOLLERANZA_OROLOGIO:
        raise ValidationAppError(
            f"La data {cosa} non può essere nel futuro.",
            details={"occurred_at": occurred_at.isoformat(), "adesso": now.isoformat()},
        )
    return min(occurred_at, now)


def _validate_occurred_at(occurred_at: datetime | None) -> datetime:
    return validate_occurred_at(occurred_at)


async def _get_unit_locked(db: AsyncSession, unit_id: uuid.UUID) -> StockUnit:
    result = await db.execute(select(StockUnit).where(StockUnit.id == unit_id).with_for_update())
    unit = result.scalar_one_or_none()
    if unit is None:
        raise NotFoundError("Unità non trovata.", details={"unit_id": str(unit_id)})
    return unit


async def _record_unit_movement(
    db: AsyncSession,
    *,
    unit: StockUnit,
    movement_type: MovementType,
    location_from_id: uuid.UUID | None,
    location_to_id: uuid.UUID | None,
    reference: str | None,
    assignee: str | None,
    reason: str | None,
    performed_by: uuid.UUID,
    occurred_at: datetime,
    delivery_note_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> StockMovement:
    new_status = apply_movement_transition(unit.status, movement_type)

    movement = StockMovement(
        occurred_at=occurred_at,
        type=movement_type,
        catalog_item_id=unit.catalog_item_id,
        stock_unit_id=unit.id,
        quantity=Decimal("1"),
        condition=unit.condition,
        location_from_id=location_from_id,
        location_to_id=location_to_id,
        delivery_note_id=delivery_note_id,
        reference=reference,
        assignee=assignee,
        reason=reason,
        performed_by=performed_by,
        notes=notes,
    )
    db.add(movement)

    unit.status = new_status
    unit.location_id = location_to_id
    await db.flush()
    return movement


async def _record_bulk_movement(
    db: AsyncSession,
    *,
    catalog_item_id: uuid.UUID,
    quantity: Decimal,
    condition: ItemCondition,
    movement_type: MovementType,
    location_from_id: uuid.UUID | None,
    location_to_id: uuid.UUID | None,
    reference: str | None,
    assignee: str | None,
    reason: str | None,
    performed_by: uuid.UUID,
    occurred_at: datetime,
    delivery_note_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> StockMovement:
    movement = StockMovement(
        occurred_at=occurred_at,
        type=movement_type,
        catalog_item_id=catalog_item_id,
        stock_unit_id=None,
        quantity=quantity,
        condition=condition,
        location_from_id=location_from_id,
        location_to_id=location_to_id,
        delivery_note_id=delivery_note_id,
        reference=reference,
        assignee=assignee,
        reason=reason,
        performed_by=performed_by,
        notes=notes,
    )
    db.add(movement)
    await db.flush()
    return movement


async def issue(
    db: AsyncSession,
    *,
    performer: User,
    location_from_id: uuid.UUID,
    reference: str,
    assignee: str | None,
    unit_lines: list[UnitLine],
    bulk_lines: list[BulkLine],
    notes: str | None,
    occurred_at: datetime | None,
) -> list[StockMovement]:
    when = _validate_occurred_at(occurred_at)
    movements: list[StockMovement] = []

    for line in unit_lines:
        unit = await _get_unit_locked(db, line.unit_id)
        movement = await _record_unit_movement(
            db,
            unit=unit,
            movement_type=MovementType.issue,
            location_from_id=location_from_id,
            location_to_id=None,
            reference=reference,
            assignee=assignee,
            reason=None,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
        movements.append(movement)

    for line in bulk_lines:
        await stock_service.lock_item_location(db, line.catalog_item_id, location_from_id)
        available = await stock_service.get_available(
            db, line.catalog_item_id, location_from_id, line.condition
        )
        if available < line.quantity:
            raise InsufficientStockError(
                f"Giacenza insufficiente: disponibili {available}, richiesti {line.quantity}",
                details={"available": float(available), "requested": float(line.quantity)},
            )
        movement = await _record_bulk_movement(
            db,
            catalog_item_id=line.catalog_item_id,
            quantity=line.quantity,
            condition=line.condition,
            movement_type=MovementType.issue,
            location_from_id=location_from_id,
            location_to_id=None,
            reference=reference,
            assignee=assignee,
            reason=None,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
        movements.append(movement)

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="movement.issue",
        entity_type="stock_movement",
        entity_id=",".join(str(m.id) for m in movements),
        details={"reference": reference, "assignee": assignee, "count": len(movements)},
    )
    return movements


async def transfer(
    db: AsyncSession,
    *,
    performer: User,
    location_from_id: uuid.UUID | None,
    location_to_id: uuid.UUID,
    unit_lines: list[UnitLine],
    bulk_lines: list[BulkLine],
    notes: str | None,
    occurred_at: datetime | None,
) -> list[StockMovement]:
    if bulk_lines and location_from_id is None:
        raise ValidationAppError(
            "L'ubicazione di partenza è obbligatoria per trasferire articoli sfusi."
        )
    when = _validate_occurred_at(occurred_at)
    movements: list[StockMovement] = []

    for line in unit_lines:
        unit = await _get_unit_locked(db, line.unit_id)
        # A serialized unit has exactly one true source: where it is right
        # now. Trusting the caller's `location_from_id` instead let a stale
        # value subtract stock from a location the piece had already left,
        # which is precisely how the ledger drifts away from the projection
        # and `v_reconciliation_errors` starts reporting anomalies.
        if unit.location_id == location_to_id:
            raise ValidationAppError(
                "Il pezzo si trova già in questa ubicazione.",
                details={"unit_id": str(unit.id)},
            )
        movement = await _record_unit_movement(
            db,
            unit=unit,
            movement_type=MovementType.transfer,
            location_from_id=unit.location_id,
            location_to_id=location_to_id,
            reference=None,
            assignee=None,
            reason=None,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
        movements.append(movement)

    for line in bulk_lines:
        await stock_service.lock_item_location(db, line.catalog_item_id, location_from_id)
        available = await stock_service.get_available(
            db, line.catalog_item_id, location_from_id, line.condition
        )
        if available < line.quantity:
            raise InsufficientStockError(
                f"Giacenza insufficiente: disponibili {available}, richiesti {line.quantity}",
                details={"available": float(available), "requested": float(line.quantity)},
            )
        movement = await _record_bulk_movement(
            db,
            catalog_item_id=line.catalog_item_id,
            quantity=line.quantity,
            condition=line.condition,
            movement_type=MovementType.transfer,
            location_from_id=location_from_id,
            location_to_id=location_to_id,
            reference=None,
            assignee=None,
            reason=None,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
        movements.append(movement)

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="movement.transfer",
        entity_type="stock_movement",
        entity_id=",".join(str(m.id) for m in movements),
        details={"count": len(movements)},
    )
    return movements


async def return_to_stock(
    db: AsyncSession,
    *,
    performer: User,
    location_to_id: uuid.UUID,
    reference: str,
    unit_lines: list[UnitLine],
    bulk_lines: list[BulkLine],
    notes: str | None,
    occurred_at: datetime | None,
) -> list[StockMovement]:
    when = _validate_occurred_at(occurred_at)
    movements: list[StockMovement] = []

    for line in unit_lines:
        unit = await _get_unit_locked(db, line.unit_id)
        movement = await _record_unit_movement(
            db,
            unit=unit,
            movement_type=MovementType.return_,
            location_from_id=None,
            location_to_id=location_to_id,
            reference=reference,
            assignee=None,
            reason=None,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
        movements.append(movement)

    for line in bulk_lines:
        movement = await _record_bulk_movement(
            db,
            catalog_item_id=line.catalog_item_id,
            quantity=line.quantity,
            condition=line.condition,
            movement_type=MovementType.return_,
            location_from_id=None,
            location_to_id=location_to_id,
            reference=reference,
            assignee=None,
            reason=None,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
        movements.append(movement)

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="movement.return",
        entity_type="stock_movement",
        entity_id=",".join(str(m.id) for m in movements),
        details={"reference": reference, "count": len(movements)},
    )
    return movements


async def rma_out(
    db: AsyncSession,
    *,
    performer: User,
    location_from_id: uuid.UUID,
    location_to_id: uuid.UUID,
    reference: str,
    unit_lines: list[UnitLine],
    notes: str | None,
    occurred_at: datetime | None,
) -> list[StockMovement]:
    when = _validate_occurred_at(occurred_at)
    movements: list[StockMovement] = []
    for line in unit_lines:
        unit = await _get_unit_locked(db, line.unit_id)
        movement = await _record_unit_movement(
            db,
            unit=unit,
            movement_type=MovementType.rma_out,
            location_from_id=location_from_id,
            location_to_id=location_to_id,
            reference=reference,
            assignee=None,
            reason=None,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
        movements.append(movement)

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="movement.rma_out",
        entity_type="stock_movement",
        entity_id=",".join(str(m.id) for m in movements),
        details={"reference": reference, "count": len(movements)},
    )
    return movements


async def rma_in(
    db: AsyncSession,
    *,
    performer: User,
    location_from_id: uuid.UUID,
    location_to_id: uuid.UUID,
    reference: str,
    unit_lines: list[UnitLine],
    notes: str | None,
    occurred_at: datetime | None,
) -> list[StockMovement]:
    when = _validate_occurred_at(occurred_at)
    movements: list[StockMovement] = []
    for line in unit_lines:
        unit = await _get_unit_locked(db, line.unit_id)
        movement = await _record_unit_movement(
            db,
            unit=unit,
            movement_type=MovementType.rma_in,
            location_from_id=location_from_id,
            location_to_id=location_to_id,
            reference=reference,
            assignee=None,
            reason=None,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
        movements.append(movement)

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="movement.rma_in",
        entity_type="stock_movement",
        entity_id=",".join(str(m.id) for m in movements),
        details={"reference": reference, "count": len(movements)},
    )
    return movements


async def adjust(
    db: AsyncSession,
    *,
    performer: User,
    reason: str,
    unit_line: UnitLine | None,
    bulk_line: BulkLine | None,
    location_from_id: uuid.UUID | None,
    location_to_id: uuid.UUID | None,
    allow_negative: bool,
    occurred_at: datetime | None,
    notes: str | None,
) -> StockMovement:
    _validate_reason(MovementType.adjustment, reason)
    when = _validate_occurred_at(occurred_at)

    if unit_line is not None:
        unit = await _get_unit_locked(db, unit_line.unit_id)
        movement = await _record_unit_movement(
            db,
            unit=unit,
            movement_type=MovementType.adjustment,
            location_from_id=location_from_id,
            location_to_id=location_to_id,
            reference=None,
            assignee=None,
            reason=reason,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
    elif bulk_line is not None:
        if not allow_negative:
            await stock_service.lock_item_location(db, bulk_line.catalog_item_id, location_from_id)
            available = await stock_service.get_available(
                db, bulk_line.catalog_item_id, location_from_id, bulk_line.condition
            )
            if location_from_id is not None and available < bulk_line.quantity:
                raise InsufficientStockError(
                    f"Rettifica rifiutata: disponibili {available}, richiesti {bulk_line.quantity}. "
                    "Usare allow_negative se intenzionale.",
                    details={"available": float(available), "requested": float(bulk_line.quantity)},
                )
        movement = await _record_bulk_movement(
            db,
            catalog_item_id=bulk_line.catalog_item_id,
            quantity=bulk_line.quantity,
            condition=bulk_line.condition,
            movement_type=MovementType.adjustment,
            location_from_id=location_from_id,
            location_to_id=location_to_id,
            reference=None,
            assignee=None,
            reason=reason,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
    else:
        raise ValidationAppError("Specificare un'unità serializzata oppure un articolo sfuso.")

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="movement.adjustment",
        entity_type="stock_movement",
        entity_id=str(movement.id),
        details={"reason": reason, "allow_negative": allow_negative},
    )
    return movement


async def scrap(
    db: AsyncSession,
    *,
    performer: User,
    reason: str,
    location_from_id: uuid.UUID,
    unit_line: UnitLine | None,
    bulk_line: BulkLine | None,
    occurred_at: datetime | None,
    notes: str | None,
) -> StockMovement:
    _validate_reason(MovementType.scrap, reason)
    when = _validate_occurred_at(occurred_at)

    if unit_line is not None:
        unit = await _get_unit_locked(db, unit_line.unit_id)
        movement = await _record_unit_movement(
            db,
            unit=unit,
            movement_type=MovementType.scrap,
            location_from_id=location_from_id,
            location_to_id=None,
            reference=None,
            assignee=None,
            reason=reason,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
    elif bulk_line is not None:
        await stock_service.lock_item_location(db, bulk_line.catalog_item_id, location_from_id)
        available = await stock_service.get_available(
            db, bulk_line.catalog_item_id, location_from_id, bulk_line.condition
        )
        if available < bulk_line.quantity:
            raise InsufficientStockError(
                f"Giacenza insufficiente per rottamare: disponibili {available}, "
                f"richiesti {bulk_line.quantity}",
                details={"available": float(available), "requested": float(bulk_line.quantity)},
            )
        movement = await _record_bulk_movement(
            db,
            catalog_item_id=bulk_line.catalog_item_id,
            quantity=bulk_line.quantity,
            condition=bulk_line.condition,
            movement_type=MovementType.scrap,
            location_from_id=location_from_id,
            location_to_id=None,
            reference=None,
            assignee=None,
            reason=reason,
            performed_by=performer.id,
            occurred_at=when,
            notes=notes,
        )
    else:
        raise ValidationAppError("Specificare un'unità serializzata oppure un articolo sfuso.")

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="movement.scrap",
        entity_type="stock_movement",
        entity_id=str(movement.id),
        details={"reason": reason},
    )
    return movement


async def reverse(
    db: AsyncSession, *, performer: User, movement_id: uuid.UUID, reason: str
) -> StockMovement:
    if not reason or len(reason.strip()) < MIN_REASON_LENGTH:
        raise ValidationAppError(
            f"Il campo 'reason' è obbligatorio (minimo {MIN_REASON_LENGTH} caratteri) per uno storno."
        )

    result = await db.execute(select(StockMovement).where(StockMovement.id == movement_id))
    original = result.scalar_one_or_none()
    if original is None:
        raise NotFoundError("Movimento non trovato.", details={"movement_id": str(movement_id)})

    already = await db.execute(
        select(StockMovement).where(StockMovement.reverses_id == movement_id)
    )
    if already.scalar_one_or_none() is not None:
        raise AlreadyReversedError(
            "Questo movimento è già stato stornato in precedenza.",
            details={"movement_id": str(movement_id)},
        )

    when = datetime.now(UTC)

    if original.stock_unit_id is not None:
        unit = await _get_unit_locked(db, original.stock_unit_id)
        reverse_type = _reverse_movement_type(original.type)
        new_status = apply_movement_transition(unit.status, reverse_type)
        # Undo from where the piece actually is, not from where the original
        # movement left it: if it has moved since, `original.location_to_id`
        # is stale and subtracting stock there desynchronises the ledger from
        # the projection (an anomaly in `v_reconciliation_errors`).
        reverse_movement = StockMovement(
            occurred_at=when,
            type=reverse_type,
            catalog_item_id=original.catalog_item_id,
            stock_unit_id=original.stock_unit_id,
            quantity=Decimal("1"),
            condition=original.condition,
            location_from_id=unit.location_id,
            location_to_id=original.location_from_id,
            delivery_note_id=None,
            reference=original.reference,
            assignee=None,
            reason=reason,
            reverses_id=original.id,
            performed_by=performer.id,
        )
        db.add(reverse_movement)
        unit.status = new_status
        unit.location_id = original.location_from_id
    else:
        reverse_movement = StockMovement(
            occurred_at=when,
            type=original.type,
            catalog_item_id=original.catalog_item_id,
            stock_unit_id=None,
            quantity=original.quantity,
            condition=original.condition,
            location_from_id=original.location_to_id,
            location_to_id=original.location_from_id,
            delivery_note_id=None,
            reference=original.reference,
            assignee=None,
            reason=reason,
            reverses_id=original.id,
            performed_by=performer.id,
        )
        db.add(reverse_movement)

    await db.flush()

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="movement.reverse",
        entity_type="stock_movement",
        entity_id=str(reverse_movement.id),
        details={"reverses": str(movement_id), "reason": reason},
    )
    return reverse_movement


def _reverse_movement_type(original: MovementType) -> MovementType:
    inverse = {
        MovementType.issue: MovementType.return_,
        MovementType.return_: MovementType.issue,
        MovementType.rma_out: MovementType.rma_in,
        MovementType.rma_in: MovementType.rma_out,
        MovementType.transfer: MovementType.transfer,
        MovementType.adjustment: MovementType.adjustment,
        MovementType.scrap: MovementType.adjustment,
        MovementType.receipt: MovementType.adjustment,
    }
    return inverse[original]
