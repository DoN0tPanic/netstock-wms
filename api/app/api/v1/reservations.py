import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.deps import CurrentUser, DbSession, require_role
from app.models.enums import ReservationStatus, UserRole
from app.models.reservations import Reservation
from app.models.users import User
from app.schemas.common import Page
from app.schemas.reservations import (
    ReservationCreate,
    ReservationFulfilRequest,
    ReservationResponse,
)
from app.services import reservations as reservation_service

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.get("", response_model=Page[ReservationResponse])
async def list_reservations(
    db: DbSession,
    user: CurrentUser,
    status: ReservationStatus | None = None,
    item: uuid.UUID | None = None,
    reference: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> Any:
    page_size = min(page_size, 200)
    filters = []
    if status:
        filters.append(Reservation.status == status)
    if item:
        filters.append(Reservation.catalog_item_id == item)
    if reference:
        filters.append(Reservation.reference.ilike(f"%{reference}%"))

    total = (
        await db.execute(select(func.count()).select_from(Reservation).where(*filters))
    ).scalar_one()
    stmt = select(Reservation).where(*filters).offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(stmt)).scalars().all()
    return Page(items=list(items), total=total, page=page, page_size=page_size)


@router.post("", response_model=ReservationResponse, status_code=201)
async def create_reservation(
    payload: ReservationCreate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    return await reservation_service.create_reservation(
        db,
        performer=user,
        catalog_item_id=payload.catalog_item_id,
        stock_unit_id=payload.stock_unit_id,
        quantity=payload.quantity,
        location_id=payload.location_id,
        reference=payload.reference,
        requested_by=payload.requested_by,
        expires_at=payload.expires_at,
        notes=payload.notes,
    )


@router.post("/{reservation_id}/cancel", response_model=ReservationResponse)
async def cancel_reservation(
    reservation_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    return await reservation_service.cancel_reservation(
        db, performer=user, reservation_id=reservation_id
    )


@router.post("/{reservation_id}/fulfil", response_model=ReservationResponse)
async def fulfil_reservation(
    reservation_id: uuid.UUID,
    payload: ReservationFulfilRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    return await reservation_service.fulfil_reservation(
        db, performer=user, reservation_id=reservation_id, movement_id=payload.movement_id
    )
