import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbSession, require_role
from app.exceptions import NotFoundError, ValidationAppError
from app.models.delivery import DeliveryNote, DeliveryNoteLine
from app.models.enums import UserRole
from app.models.movements import StockMovement
from app.models.users import User
from app.schemas.common import Page
from app.schemas.delivery import (
    DeliveryNoteCloseRequest,
    DeliveryNoteCreate,
    DeliveryNoteDetailResponse,
    DeliveryNoteLineCreate,
    DeliveryNoteLineResponse,
    DeliveryNoteResponse,
    DeliveryNoteUpdate,
    ReceiveRequest,
    ReceiveResponse,
)
from app.services.audit import write_audit
from app.services.receiving import ReceiveLine, SerialInput, receive_delivery_note

router = APIRouter(prefix="/delivery-notes", tags=["delivery-notes"])


@router.get("", response_model=Page[DeliveryNoteResponse])
async def list_delivery_notes(
    db: DbSession,
    user: CurrentUser,
    q: str | None = None,
    supplier: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    is_closed: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> Any:
    page_size = min(page_size, 200)
    filters = []
    if q:
        filters.append(DeliveryNote.number.ilike(f"%{q}%"))
    if supplier:
        filters.append(DeliveryNote.supplier_id == supplier)
    if date_from:
        filters.append(DeliveryNote.note_date >= date_from)
    if date_to:
        filters.append(DeliveryNote.note_date <= date_to)
    if is_closed is not None:
        filters.append(DeliveryNote.is_closed == is_closed)

    total = (
        await db.execute(select(func.count()).select_from(DeliveryNote).where(*filters))
    ).scalar_one()
    stmt = (
        select(DeliveryNote)
        .where(*filters)
        .order_by(DeliveryNote.note_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = (await db.execute(stmt)).scalars().all()
    return Page(items=list(items), total=total, page=page, page_size=page_size)


@router.post("", response_model=DeliveryNoteDetailResponse, status_code=201)
async def create_delivery_note(
    payload: DeliveryNoteCreate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    note = DeliveryNote(
        number=payload.number,
        note_date=payload.note_date,
        supplier_id=payload.supplier_id,
        po_number=payload.po_number,
        carrier=payload.carrier,
        tracking_number=payload.tracking_number,
        notes=payload.notes,
        received_by=user.id,
    )
    db.add(note)
    await db.flush()

    for index, line_payload in enumerate(payload.lines, start=1):
        line = DeliveryNoteLine(
            delivery_note_id=note.id,
            line_number=index,
            catalog_item_id=line_payload.catalog_item_id,
            qty_expected=line_payload.qty_expected,
            condition=line_payload.condition,
            notes=line_payload.notes,
        )
        db.add(line)
    await db.flush()

    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="delivery_note.create",
        entity_type="delivery_note",
        entity_id=str(note.id),
        details={"number": note.number, "lines": len(payload.lines)},
    )

    result = await db.execute(
        select(DeliveryNote)
        .options(selectinload(DeliveryNote.lines))
        .where(DeliveryNote.id == note.id)
    )
    return result.scalar_one()


@router.get("/{note_id}", response_model=DeliveryNoteDetailResponse)
async def get_delivery_note(note_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Any:
    result = await db.execute(
        select(DeliveryNote)
        .options(selectinload(DeliveryNote.lines))
        .where(DeliveryNote.id == note_id)
    )
    note = result.scalar_one_or_none()
    if note is None:
        raise NotFoundError("Bolla non trovata.", details={"id": str(note_id)})
    return note


@router.patch("/{note_id}", response_model=DeliveryNoteDetailResponse)
async def update_delivery_note(
    note_id: uuid.UUID,
    payload: DeliveryNoteUpdate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    note = await db.get(DeliveryNote, note_id)
    if note is None:
        raise NotFoundError("Bolla non trovata.", details={"id": str(note_id)})
    if note.is_closed:
        raise ValidationAppError(
            "La bolla è chiusa: solo la testata di una bolla aperta è modificabile."
        )
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(note, key, value)
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="delivery_note.update",
        entity_type="delivery_note",
        entity_id=str(note.id),
        details={"changed_fields": changes},
    )
    result = await db.execute(
        select(DeliveryNote)
        .options(selectinload(DeliveryNote.lines))
        .where(DeliveryNote.id == note.id)
    )
    return result.scalar_one()


@router.post("/{note_id}/lines", response_model=DeliveryNoteLineResponse, status_code=201)
async def add_delivery_note_line(
    note_id: uuid.UUID,
    payload: DeliveryNoteLineCreate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    note = await db.get(DeliveryNote, note_id)
    if note is None:
        raise NotFoundError("Bolla non trovata.", details={"id": str(note_id)})
    if note.is_closed:
        raise ValidationAppError("La bolla è chiusa: non è possibile aggiungere righe.")

    max_line = (
        await db.execute(
            select(func.coalesce(func.max(DeliveryNoteLine.line_number), 0)).where(
                DeliveryNoteLine.delivery_note_id == note_id
            )
        )
    ).scalar_one()

    line = DeliveryNoteLine(
        delivery_note_id=note_id,
        line_number=max_line + 1,
        catalog_item_id=payload.catalog_item_id,
        qty_expected=payload.qty_expected,
        condition=payload.condition,
        notes=payload.notes,
    )
    db.add(line)
    await db.flush()

    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="delivery_note.add_line",
        entity_type="delivery_note_line",
        entity_id=str(line.id),
        details={"delivery_note_id": str(note_id)},
    )
    return line


@router.post("/{note_id}/receive", response_model=ReceiveResponse, status_code=201)
async def receive(
    note_id: uuid.UUID,
    payload: ReceiveRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    lines = [
        ReceiveLine(
            line_id=line.line_id,
            condition=line.condition,
            serials=[
                SerialInput(
                    serial_number=s.serial_number,
                    mac_address=s.mac_address,
                    location_id=s.location_id,
                )
                for s in line.serials
            ],
            quantity=line.quantity,
        )
        for line in payload.lines
    ]
    result = await receive_delivery_note(
        db,
        performer=user,
        delivery_note_id=note_id,
        location_id=payload.location_id,
        lines=lines,
        confirm_warnings=set(payload.confirm_warnings),
        occurred_at=payload.occurred_at,
    )
    return ReceiveResponse(
        created_unit_ids=result.created_unit_ids,
        movement_ids=result.movement_ids,
        delivery_note_closed=result.delivery_note_closed,
    )


@router.delete("/{note_id}", status_code=204)
async def delete_delivery_note(
    note_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> None:
    """Delete a delivery note typed in by mistake.

    Allowed only while nothing has been received against it: once a single
    piece has come in, the note is part of that piece's provenance and the
    movements referencing it are append-only, so it can no longer be removed.
    """
    note = await db.get(DeliveryNote, note_id)
    if note is None:
        raise NotFoundError("Bolla non trovata.", details={"id": str(note_id)})

    received = (
        await db.execute(
            select(func.coalesce(func.sum(DeliveryNoteLine.qty_received), 0)).where(
                DeliveryNoteLine.delivery_note_id == note_id
            )
        )
    ).scalar_one()
    movements = (
        await db.execute(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.delivery_note_id == note_id)
        )
    ).scalar_one()
    if received or movements:
        raise ValidationAppError(
            "Questa bolla ha già della merce ricevuta: non può essere eliminata. "
            "Per annullare la ricezione usa uno storno dai Movimenti.",
            details={"qty_received": str(received), "movimenti": int(movements)},
        )

    await db.execute(delete(DeliveryNoteLine).where(DeliveryNoteLine.delivery_note_id == note_id))
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="delivery_note.delete",
        entity_type="delivery_note",
        entity_id=str(note_id),
        details={"number": note.number},
    )
    await db.delete(note)
    await db.flush()


@router.post("/{note_id}/close", response_model=DeliveryNoteResponse)
async def close_delivery_note(
    note_id: uuid.UUID,
    payload: DeliveryNoteCloseRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    note = await db.get(DeliveryNote, note_id)
    if note is None:
        raise NotFoundError("Bolla non trovata.", details={"id": str(note_id)})
    if note.is_closed:
        raise ValidationAppError("La bolla è già chiusa.")
    if not payload.reason or len(payload.reason.strip()) < 10:
        raise ValidationAppError(
            "Indicare una motivazione di almeno 10 caratteri per la chiusura manuale."
        )

    note.is_closed = True
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="delivery_note.close_manual",
        entity_type="delivery_note",
        entity_id=str(note.id),
        details={"reason": payload.reason},
    )
    return note
