import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConfirmationRequiredError, NotFoundError, ValidationAppError
from app.models.catalog import CatalogItem
from app.models.delivery import DeliveryNote, DeliveryNoteLine
from app.models.enums import ItemCondition, MovementType
from app.models.movements import StockMovement
from app.models.stock import StockUnit
from app.models.users import User
from app.services.audit import write_audit
from app.services.movements import validate_occurred_at
from app.services.serials import matches_pattern, normalize_mac, normalize_serial


@dataclass
class SerialInput:
    serial_number: str
    mac_address: str | None = None
    location_id: uuid.UUID | None = None  # overrides the request-level default for this piece


@dataclass
class ReceiveLine:
    line_id: uuid.UUID
    condition: ItemCondition
    serials: list[SerialInput] = field(default_factory=list)
    quantity: Decimal | None = None


@dataclass
class FreeReceiveLine:
    catalog_item_id: uuid.UUID
    condition: ItemCondition
    serials: list[SerialInput] = field(default_factory=list)
    quantity: Decimal | None = None


@dataclass
class ReceiveResult:
    created_unit_ids: list[uuid.UUID]
    movement_ids: list[uuid.UUID]
    warnings: list[dict]
    delivery_note_closed: bool


async def _validate_and_normalize_serial(
    db: AsyncSession,
    *,
    item: CatalogItem,
    serial_input: SerialInput,
    seen_in_request: set[str],
    confirm_warnings: set[str],
    warnings: list[dict],
) -> SerialInput:
    serial = normalize_serial(serial_input.serial_number)
    if not serial:
        raise ValidationAppError("Seriale vuoto non ammesso.")
    if serial in seen_in_request:
        raise ValidationAppError(
            f"Seriale duplicato nella lista corrente: {serial}",
            details={"serial_number": serial},
        )
    seen_in_request.add(serial)

    mac = normalize_mac(serial_input.mac_address) if serial_input.mac_address else None

    same_model = await db.execute(
        select(StockUnit).where(
            StockUnit.catalog_item_id == item.id, StockUnit.serial_number == serial
        )
    )
    if same_model.scalar_one_or_none() is not None:
        raise ValidationAppError(
            f"Seriale già presente per questo articolo: {serial}",
            details={"serial_number": serial},
        )

    other_model = await db.execute(select(StockUnit).where(StockUnit.serial_number == serial))
    if other_model.scalar_one_or_none() is not None:
        code = "duplicate_serial_other_model"
        if code not in confirm_warnings:
            warnings.append(
                {
                    "code": code,
                    "message": f"Il seriale {serial} risulta già usato su un altro modello.",
                    "serial_number": serial,
                }
            )

    if not matches_pattern(serial, item.serial_pattern):
        code = "format_mismatch"
        if code not in confirm_warnings:
            warnings.append(
                {
                    "code": code,
                    "message": (
                        f"Il seriale {serial} non rispetta il formato atteso per "
                        f"{item.part_number}."
                    ),
                    "serial_number": serial,
                }
            )

    return SerialInput(serial_number=serial, mac_address=mac, location_id=serial_input.location_id)


async def _create_serial_unit_and_movement(
    db: AsyncSession,
    *,
    item: CatalogItem,
    serial_input: SerialInput,
    condition: ItemCondition,
    location_id: uuid.UUID,
    delivery_note_line_id: uuid.UUID | None,
    delivery_note_id: uuid.UUID | None,
    when: datetime,
    performer: User,
    reference: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    unit_location_id = serial_input.location_id or location_id
    unit = StockUnit(
        catalog_item_id=item.id,
        serial_number=serial_input.serial_number,
        mac_address=serial_input.mac_address,
        condition=condition,
        location_id=unit_location_id,
        delivery_note_line_id=delivery_note_line_id,
    )
    db.add(unit)
    await db.flush()

    movement = StockMovement(
        occurred_at=when,
        type=MovementType.receipt,
        catalog_item_id=item.id,
        stock_unit_id=unit.id,
        quantity=Decimal("1"),
        condition=unit.condition,
        location_from_id=None,
        location_to_id=unit_location_id,
        delivery_note_id=delivery_note_id,
        reference=reference,
        performed_by=performer.id,
    )
    db.add(movement)
    await db.flush()
    return unit.id, movement.id


async def _create_bulk_movement(
    db: AsyncSession,
    *,
    item: CatalogItem,
    quantity: Decimal,
    condition: ItemCondition,
    location_id: uuid.UUID,
    delivery_note_id: uuid.UUID | None,
    when: datetime,
    performer: User,
    reference: str | None = None,
) -> uuid.UUID:
    movement = StockMovement(
        occurred_at=when,
        type=MovementType.receipt,
        catalog_item_id=item.id,
        stock_unit_id=None,
        quantity=quantity,
        condition=condition,
        location_from_id=None,
        location_to_id=location_id,
        delivery_note_id=delivery_note_id,
        reference=reference,
        performed_by=performer.id,
    )
    db.add(movement)
    await db.flush()
    return movement.id


async def receive_delivery_note(
    db: AsyncSession,
    *,
    performer: User,
    delivery_note_id: uuid.UUID,
    location_id: uuid.UUID,
    lines: list[ReceiveLine],
    confirm_warnings: set[str],
    occurred_at: datetime | None,
) -> ReceiveResult:
    note_result = await db.execute(
        select(DeliveryNote).where(DeliveryNote.id == delivery_note_id).with_for_update()
    )
    note = note_result.scalar_one_or_none()
    if note is None:
        raise NotFoundError(
            "Bolla non trovata.", details={"delivery_note_id": str(delivery_note_id)}
        )
    if note.is_closed:
        raise ValidationAppError("La bolla è già chiusa: nessuna ricezione ulteriore consentita.")

    when = validate_occurred_at(occurred_at, cosa="di ricezione")

    warnings: list[dict] = []
    plan: list[dict] = []

    for line in lines:
        line_result = await db.execute(
            select(DeliveryNoteLine)
            .where(
                DeliveryNoteLine.id == line.line_id,
                DeliveryNoteLine.delivery_note_id == delivery_note_id,
            )
            .with_for_update()
        )
        ddt_line = line_result.scalar_one_or_none()
        if ddt_line is None:
            raise NotFoundError("Riga bolla non trovata.", details={"line_id": str(line.line_id)})

        item_result = await db.execute(
            select(CatalogItem).where(CatalogItem.id == ddt_line.catalog_item_id)
        )
        item = item_result.scalar_one()

        if item.is_serialized:
            seen_in_request: set[str] = set()
            normalized_serials: list[SerialInput] = []
            for serial_input in line.serials:
                normalized_serials.append(
                    await _validate_and_normalize_serial(
                        db,
                        item=item,
                        serial_input=serial_input,
                        seen_in_request=seen_in_request,
                        confirm_warnings=confirm_warnings,
                        warnings=warnings,
                    )
                )

            # Zero seriali su un articolo serializzato non è una ricezione da
            # zero pezzi: è una riga incompleta. Senza questo controllo il
            # piano proseguiva con `quantity=None` e finiva contro il vincolo
            # NOT NULL della colonna, cioè un 500 al posto di una spiegazione.
            if not normalized_serials:
                raise ValidationAppError(
                    f"«{item.part_number}» è un articolo serializzato: per registrarne la "
                    "ricezione serve almeno un numero seriale."
                )

            new_qty_received = ddt_line.qty_received + len(normalized_serials)
            plan.append(
                {
                    "ddt_line": ddt_line,
                    "item": item,
                    "serials": normalized_serials,
                    "quantity": None,
                    "condition": line.condition,
                }
            )
        else:
            quantity = line.quantity or Decimal("0")
            if quantity <= 0:
                raise ValidationAppError("La quantità ricevuta deve essere maggiore di zero.")
            new_qty_received = ddt_line.qty_received + quantity
            plan.append(
                {
                    "ddt_line": ddt_line,
                    "item": item,
                    "serials": [],
                    "quantity": quantity,
                    "condition": line.condition,
                }
            )

        if new_qty_received > ddt_line.qty_expected:
            code = "over_receipt"
            if code not in confirm_warnings:
                warnings.append(
                    {
                        "code": code,
                        "message": (
                            f"Sovra-ricezione su {item.part_number}: attesi "
                            f"{ddt_line.qty_expected}, totale ricevuto {new_qty_received}."
                        ),
                        "line_id": str(ddt_line.id),
                    }
                )

    if warnings:
        raise ConfirmationRequiredError(
            "Sono presenti avvisi da confermare prima di registrare la ricezione.",
            details={"warnings": warnings},
        )

    created_unit_ids: list[uuid.UUID] = []
    movement_ids: list[uuid.UUID] = []

    for entry in plan:
        ddt_line: DeliveryNoteLine = entry["ddt_line"]
        item: CatalogItem = entry["item"]

        if entry["serials"]:
            for serial_input in entry["serials"]:
                unit_id, movement_id = await _create_serial_unit_and_movement(
                    db,
                    item=item,
                    serial_input=serial_input,
                    condition=entry["condition"],
                    location_id=location_id,
                    delivery_note_line_id=ddt_line.id,
                    delivery_note_id=delivery_note_id,
                    when=when,
                    performer=performer,
                )
                created_unit_ids.append(unit_id)
                movement_ids.append(movement_id)

            ddt_line.qty_received = ddt_line.qty_received + len(entry["serials"])
        else:
            quantity = entry["quantity"]
            movement_id = await _create_bulk_movement(
                db,
                item=item,
                quantity=quantity,
                condition=entry["condition"],
                location_id=location_id,
                delivery_note_id=delivery_note_id,
                when=when,
                performer=performer,
            )
            movement_ids.append(movement_id)
            ddt_line.qty_received = ddt_line.qty_received + quantity

    await db.flush()

    all_lines_result = await db.execute(
        select(DeliveryNoteLine).where(DeliveryNoteLine.delivery_note_id == delivery_note_id)
    )
    all_lines = all_lines_result.scalars().all()
    fully_received = all(dl.qty_received >= dl.qty_expected for dl in all_lines)
    if fully_received:
        note.is_closed = True

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="delivery_note.receive",
        entity_type="delivery_note",
        entity_id=str(delivery_note_id),
        details={
            "units_created": len(created_unit_ids),
            "movements_created": len(movement_ids),
            "closed": note.is_closed,
            "confirmed_warnings": list(confirm_warnings),
        },
    )

    return ReceiveResult(
        created_unit_ids=created_unit_ids,
        movement_ids=movement_ids,
        warnings=[],
        delivery_note_closed=note.is_closed,
    )


async def receive_free_stock(
    db: AsyncSession,
    *,
    performer: User,
    location_id: uuid.UUID,
    lines: list[FreeReceiveLine],
    confirm_warnings: set[str],
    occurred_at: datetime | None,
    reference: str | None = None,
) -> ReceiveResult:
    """Receive stock that has no delivery note at all (e.g. found equipment,
    gear handed over without paperwork). A note can be linked afterwards on
    each resulting unit — see `attach_delivery_note` in `app.api.v1.units`.

    `reference` finisce su ogni movimento generato. Serve a chi legge il
    registro fra due anni: senza, il carico iniziale importato dall'Excel
    sarebbe indistinguibile da merce trovata in magazzino e registrata a mano.
    """
    when = validate_occurred_at(occurred_at, cosa="di ricezione")

    warnings: list[dict] = []
    plan: list[dict] = []

    for line in lines:
        item_result = await db.execute(
            select(CatalogItem).where(CatalogItem.id == line.catalog_item_id)
        )
        item = item_result.scalar_one_or_none()
        if item is None:
            raise NotFoundError(
                "Articolo non trovato.", details={"catalog_item_id": str(line.catalog_item_id)}
            )

        if item.is_serialized:
            seen_in_request: set[str] = set()
            normalized_serials: list[SerialInput] = []
            for serial_input in line.serials:
                normalized_serials.append(
                    await _validate_and_normalize_serial(
                        db,
                        item=item,
                        serial_input=serial_input,
                        seen_in_request=seen_in_request,
                        confirm_warnings=confirm_warnings,
                        warnings=warnings,
                    )
                )
            # Zero seriali su un articolo serializzato non è una ricezione da
            # zero pezzi: è una riga incompleta. Senza questo controllo il
            # piano proseguiva con `quantity=None` e finiva contro il vincolo
            # NOT NULL della colonna, cioè un 500 al posto di una spiegazione.
            if not normalized_serials:
                raise ValidationAppError(
                    f"«{item.part_number}» è un articolo serializzato: per registrarne la "
                    "ricezione serve almeno un numero seriale."
                )

            plan.append(
                {
                    "item": item,
                    "serials": normalized_serials,
                    "quantity": None,
                    "condition": line.condition,
                }
            )
        else:
            quantity = line.quantity or Decimal("0")
            if quantity <= 0:
                raise ValidationAppError("La quantità ricevuta deve essere maggiore di zero.")
            plan.append(
                {"item": item, "serials": [], "quantity": quantity, "condition": line.condition}
            )

    if warnings:
        raise ConfirmationRequiredError(
            "Sono presenti avvisi da confermare prima di registrare la ricezione.",
            details={"warnings": warnings},
        )

    created_unit_ids: list[uuid.UUID] = []
    movement_ids: list[uuid.UUID] = []

    for entry in plan:
        item: CatalogItem = entry["item"]
        if entry["serials"]:
            for serial_input in entry["serials"]:
                unit_id, movement_id = await _create_serial_unit_and_movement(
                    db,
                    item=item,
                    serial_input=serial_input,
                    condition=entry["condition"],
                    location_id=location_id,
                    delivery_note_line_id=None,
                    delivery_note_id=None,
                    when=when,
                    performer=performer,
                    reference=reference,
                )
                created_unit_ids.append(unit_id)
                movement_ids.append(movement_id)
        else:
            movement_id = await _create_bulk_movement(
                db,
                item=item,
                quantity=entry["quantity"],
                condition=entry["condition"],
                location_id=location_id,
                delivery_note_id=None,
                when=when,
                performer=performer,
                reference=reference,
            )
            movement_ids.append(movement_id)

    await db.flush()

    await write_audit(
        db,
        actor=performer,
        actor_username=performer.username,
        action="stock.receive_without_note",
        entity_type="stock_unit",
        entity_id=None,
        details={
            "units_created": len(created_unit_ids),
            "movements_created": len(movement_ids),
            "confirmed_warnings": list(confirm_warnings),
        },
    )

    return ReceiveResult(
        created_unit_ids=created_unit_ids,
        movement_ids=movement_ids,
        warnings=[],
        delivery_note_closed=False,
    )
