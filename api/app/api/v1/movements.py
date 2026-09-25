import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import CurrentUser, DbSession, require_role
from app.idempotenza import con_idempotenza
from app.models.catalog import CatalogItem, Location
from app.models.enums import MovementType, UserRole
from app.models.movements import StockMovement
from app.models.stock import StockUnit
from app.models.users import User
from app.schemas.common import Page
from app.schemas.stock import (
    AdjustRequest,
    BulkLineRequest,
    FreeReceiveRequest,
    FreeReceiveResponse,
    IssueRequest,
    ReturnRequest,
    ReverseRequest,
    RmaInRequest,
    RmaOutRequest,
    ScrapRequest,
    StockMovementResponse,
    TransferRequest,
    UnitLineRequest,
)
from app.services import movements as movement_service
from app.services.csv_export import csv_response
from app.services.receiving import FreeReceiveLine, SerialInput, receive_free_stock

router = APIRouter(prefix="/movements", tags=["movements"])

# Mirrors `movementTypeLabels` in the frontend so an exported file reads the
# same as the screen it was exported from.
MOVEMENT_TYPE_LABELS: dict[MovementType, str] = {
    MovementType.receipt: "Carico",
    MovementType.issue: "Uscita",
    MovementType.transfer: "Spostamento",
    MovementType.return_: "Reso",
    MovementType.rma_out: "Invio RMA",
    MovementType.rma_in: "Rientro RMA",
    MovementType.adjustment: "Rettifica",
    MovementType.scrap: "Rottamazione",
}


@router.get("", response_model=Page[StockMovementResponse])
async def list_movements(
    db: DbSession,
    user: CurrentUser,
    item: uuid.UUID | None = None,
    unit: uuid.UUID | None = None,
    type: MovementType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    # Più ubicazioni insieme, come nel magazzino: un movimento la tocca da
    # una parte o dall'altra, quindi «fra questi tre posti» vuol dire che
    # partenza o destinazione è uno dei tre.
    location: Annotated[list[uuid.UUID] | None, Query()] = None,
    reference: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> Any:
    page_size = min(page_size, 200)
    filters = []
    if item:
        filters.append(StockMovement.catalog_item_id == item)
    if unit:
        filters.append(StockMovement.stock_unit_id == unit)
    if type:
        filters.append(StockMovement.type == type)
    if date_from:
        filters.append(StockMovement.occurred_at >= date_from)
    if date_to:
        filters.append(StockMovement.occurred_at <= date_to)
    if location:
        filters.append(
            StockMovement.location_from_id.in_(location)
            | StockMovement.location_to_id.in_(location)
        )
    if reference:
        filters.append(StockMovement.reference.ilike(f"%{reference}%"))

    total = (
        await db.execute(select(func.count()).select_from(StockMovement).where(*filters))
    ).scalar_one()
    stmt = (
        select(StockMovement)
        .where(*filters)
        .order_by(StockMovement.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    await _decorate_movements(db, items)
    return Page(items=items, total=total, page=page, page_size=page_size)


# asyncpg non accetta più di 32767 parametri in una sola istruzione: è un
# limite del protocollo di PostgreSQL, non una scelta della libreria. Una
# pagina di movimenti non ci arriva neanche vicino, ma l'esportazione completa
# decora *tutti* i movimenti in una volta: con più di trentaduemila pezzi
# distinti nello storico, l'archivio completo smetteva di scaricarsi — e non
# con un messaggio, con un errore 500. Lo scaglione tiene le istruzioni sotto
# il limite senza che chi chiama debba saperlo.
_MASSIMO_PARAMETRI = 20_000


async def _mappa_a_scaglioni(
    db: DbSession, colonna_id: Any, colonna_valore: Any, identificativi: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Any]:
    """Da identificativi a valori, in istruzioni abbastanza piccole da girare."""
    elenco = list(identificativi)
    risultato: dict[uuid.UUID, Any] = {}
    for inizio in range(0, len(elenco), _MASSIMO_PARAMETRI):
        scaglione = elenco[inizio : inizio + _MASSIMO_PARAMETRI]
        righe = await db.execute(
            select(colonna_id, colonna_valore).where(colonna_id.in_(scaglione))
        )
        risultato.update(dict(righe.all()))
    return risultato


async def _decorate_movements(db: DbSession, movements: list[StockMovement]) -> None:
    """Attach human-readable labels to a page of movements.

    The log is unusable when every column is a UUID: the operator needs to see
    which model and which serial moved, between which locations, and by whom.
    Resolved in a handful of set-based lookups rather than per row.
    """
    if not movements:
        return

    item_ids = {m.catalog_item_id for m in movements}
    unit_ids = {m.stock_unit_id for m in movements if m.stock_unit_id}
    location_ids = {m.location_from_id for m in movements if m.location_from_id} | {
        m.location_to_id for m in movements if m.location_to_id
    }
    user_ids = {m.performed_by for m in movements}
    movement_ids = {m.id for m in movements}

    part_numbers = await _mappa_a_scaglioni(
        db, CatalogItem.id, CatalogItem.part_number, item_ids
    )
    serials = await _mappa_a_scaglioni(db, StockUnit.id, StockUnit.serial_number, unit_ids)
    location_codes = await _mappa_a_scaglioni(db, Location.id, Location.code, location_ids)
    usernames = await _mappa_a_scaglioni(db, User.id, User.username, user_ids)
    reversed_ids: set[uuid.UUID] = set()
    elenco_movimenti = list(movement_ids)
    for inizio in range(0, len(elenco_movimenti), _MASSIMO_PARAMETRI):
        scaglione = elenco_movimenti[inizio : inizio + _MASSIMO_PARAMETRI]
        reversed_ids.update(
            row[0]
            for row in (
                await db.execute(
                    select(StockMovement.reverses_id).where(
                        StockMovement.reverses_id.in_(scaglione)
                    )
                )
            ).all()
        )

    for movement in movements:
        movement.part_number = part_numbers.get(movement.catalog_item_id)
        movement.serial_number = serials.get(movement.stock_unit_id)
        movement.location_from_code = location_codes.get(movement.location_from_id)
        movement.location_to_code = location_codes.get(movement.location_to_id)
        movement.performed_by_username = usernames.get(movement.performed_by)
        movement.is_reversed = movement.id in reversed_ids


MOVEMENT_HEADERS = [
    "Data",
    "Tipo",
    "Articolo",
    "Seriale",
    "Quantità",
    "Da",
    "A",
    "Eseguito da",
    "Riferimento",
    "Motivazione",
    "Stornato",
]


async def movements_table(
    db: AsyncSession, date_from: datetime | None = None, date_to: datetime | None = None
) -> list[list[Any]]:
    """Il registro dei movimenti, pronto da scrivere.

    Passa dagli stessi nomi leggibili della pagina Movimenti: un foglio pieno
    di UUID non è un'esportazione che qualcuno possa usare.
    """
    filters = []
    if date_from:
        filters.append(StockMovement.occurred_at >= date_from)
    if date_to:
        filters.append(StockMovement.occurred_at <= date_to)
    stmt = select(StockMovement).where(*filters).order_by(StockMovement.occurred_at.desc())
    rows = list((await db.execute(stmt)).scalars().all())
    await _decorate_movements(db, rows)
    return [
        [
            m.occurred_at.isoformat(),
            MOVEMENT_TYPE_LABELS.get(m.type, m.type.value),
            m.part_number or "",
            m.serial_number or "",
            str(m.quantity),
            m.location_from_code or "",
            m.location_to_code or "",
            m.performed_by_username or "",
            m.reference or "",
            m.reason or "",
            "sì" if m.is_reversed else "",
        ]
        for m in rows
    ]


@router.get("/export")
async def export_movements(
    db: DbSession,
    user: CurrentUser,
    format: Literal["csv"] = "csv",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Any:
    return csv_response(
        "movimenti.csv", MOVEMENT_HEADERS, await movements_table(db, date_from, date_to)
    )


def _split_issue_items(
    items: list[UnitLineRequest | BulkLineRequest],
) -> tuple[list[movement_service.UnitLine], list[movement_service.BulkLine]]:
    unit_lines = [
        movement_service.UnitLine(unit_id=i.unit_id)
        for i in items
        if isinstance(i, UnitLineRequest)
    ]
    bulk_lines = [
        movement_service.BulkLine(
            catalog_item_id=i.catalog_item_id, quantity=i.quantity, condition=i.condition
        )
        for i in items
        if isinstance(i, BulkLineRequest)
    ]
    return unit_lines, bulk_lines


@router.post("/issue", response_model=list[StockMovementResponse], status_code=201)
async def issue_movement(
    request: Request,
    payload: IssueRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    async def esegui() -> Any:
        unit_lines, bulk_lines = _split_issue_items(payload.items)
        result = await movement_service.issue(
            db,
            performer=user,
            location_from_id=payload.location_from_id,
            reference=payload.reference,
            assignee=payload.assignee,
            unit_lines=unit_lines,
            bulk_lines=bulk_lines,
            notes=payload.notes,
            occurred_at=payload.occurred_at,
        )
        if payload.reservation_id is not None and result:
            from app.services.reservations import fulfil_reservation

            await fulfil_reservation(
                db, performer=user, reservation_id=payload.reservation_id, movement_id=result[0].id
            )
        return result

    return await con_idempotenza(request, db, user, esegui)


@router.post("/transfer", response_model=list[StockMovementResponse], status_code=201)
async def transfer_movement(
    request: Request,
    payload: TransferRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    async def esegui() -> Any:
        unit_lines = [movement_service.UnitLine(unit_id=uid) for uid in payload.unit_ids]
        bulk_lines = [
            movement_service.BulkLine(
                catalog_item_id=b.catalog_item_id, quantity=b.quantity, condition=b.condition
            )
            for b in payload.bulk_items
        ]
        return await movement_service.transfer(
            db,
            performer=user,
            location_from_id=payload.location_from_id,
            location_to_id=payload.location_to_id,
            unit_lines=unit_lines,
            bulk_lines=bulk_lines,
            notes=payload.notes,
            occurred_at=payload.occurred_at,
        )

    return await con_idempotenza(request, db, user, esegui)


@router.post("/return", response_model=list[StockMovementResponse], status_code=201)
async def return_movement(
    request: Request,
    payload: ReturnRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    async def esegui() -> Any:
        unit_lines = [movement_service.UnitLine(unit_id=uid) for uid in payload.unit_ids]
        bulk_lines = [
            movement_service.BulkLine(
                catalog_item_id=b.catalog_item_id, quantity=b.quantity, condition=b.condition
            )
            for b in payload.bulk_items
        ]
        return await movement_service.return_to_stock(
            db,
            performer=user,
            location_to_id=payload.location_to_id,
            reference=payload.reference,
            unit_lines=unit_lines,
            bulk_lines=bulk_lines,
            notes=payload.notes,
            occurred_at=payload.occurred_at,
        )

    return await con_idempotenza(request, db, user, esegui)


@router.post("/rma-out", response_model=list[StockMovementResponse], status_code=201)
async def rma_out_movement(
    request: Request,
    payload: RmaOutRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    async def esegui() -> Any:
        unit_lines = [movement_service.UnitLine(unit_id=uid) for uid in payload.unit_ids]
        return await movement_service.rma_out(
            db,
            performer=user,
            location_from_id=payload.location_from_id,
            location_to_id=payload.location_to_id,
            reference=payload.reference,
            unit_lines=unit_lines,
            notes=payload.notes,
            occurred_at=payload.occurred_at,
        )

    return await con_idempotenza(request, db, user, esegui)


@router.post("/rma-in", response_model=list[StockMovementResponse], status_code=201)
async def rma_in_movement(
    request: Request,
    payload: RmaInRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    async def esegui() -> Any:
        unit_lines = [movement_service.UnitLine(unit_id=uid) for uid in payload.unit_ids]
        return await movement_service.rma_in(
            db,
            performer=user,
            location_from_id=payload.location_from_id,
            location_to_id=payload.location_to_id,
            reference=payload.reference,
            unit_lines=unit_lines,
            notes=payload.notes,
            occurred_at=payload.occurred_at,
        )

    return await con_idempotenza(request, db, user, esegui)


@router.post("/receive", response_model=FreeReceiveResponse, status_code=201)
async def receive_without_note(
    request: Request,
    payload: FreeReceiveRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    async def esegui() -> Any:
        lines = [
            FreeReceiveLine(
                catalog_item_id=line.catalog_item_id,
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
        result = await receive_free_stock(
            db,
            performer=user,
            location_id=payload.location_id,
            lines=lines,
            confirm_warnings=set(payload.confirm_warnings),
            occurred_at=payload.occurred_at,
        )
        return FreeReceiveResponse(
            created_unit_ids=result.created_unit_ids, movement_ids=result.movement_ids
        )

    return await con_idempotenza(request, db, user, esegui)


@router.post("/adjust", response_model=StockMovementResponse, status_code=201)
async def adjust_movement(
    request: Request,
    payload: AdjustRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    async def esegui() -> Any:
        unit_line = movement_service.UnitLine(unit_id=payload.unit_id) if payload.unit_id else None
        bulk_line = (
            movement_service.BulkLine(
                catalog_item_id=payload.catalog_item_id,
                quantity=payload.quantity,
                condition=payload.condition,
            )
            if payload.catalog_item_id and payload.quantity
            else None
        )
        return await movement_service.adjust(
            db,
            performer=user,
            reason=payload.reason,
            unit_line=unit_line,
            bulk_line=bulk_line,
            location_from_id=payload.location_from_id,
            location_to_id=payload.location_to_id,
            allow_negative=payload.allow_negative,
            occurred_at=payload.occurred_at,
            notes=payload.notes,
        )

    return await con_idempotenza(request, db, user, esegui)


@router.post("/scrap", response_model=StockMovementResponse, status_code=201)
async def scrap_movement(
    request: Request,
    payload: ScrapRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    async def esegui() -> Any:
        unit_line = movement_service.UnitLine(unit_id=payload.unit_id) if payload.unit_id else None
        bulk_line = (
            movement_service.BulkLine(
                catalog_item_id=payload.catalog_item_id,
                quantity=payload.quantity,
                condition=payload.condition,
            )
            if payload.catalog_item_id and payload.quantity
            else None
        )
        return await movement_service.scrap(
            db,
            performer=user,
            reason=payload.reason,
            location_from_id=payload.location_from_id,
            unit_line=unit_line,
            bulk_line=bulk_line,
            occurred_at=payload.occurred_at,
            notes=payload.notes,
        )

    return await con_idempotenza(request, db, user, esegui)


@router.post("/{movement_id}/reverse", response_model=StockMovementResponse, status_code=201)
async def reverse_movement(
    request: Request,
    movement_id: uuid.UUID,
    payload: ReverseRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    async def esegui() -> Any:
        return await movement_service.reverse(
            db, performer=user, movement_id=movement_id, reason=payload.reason
        )

    return await con_idempotenza(request, db, user, esegui)
