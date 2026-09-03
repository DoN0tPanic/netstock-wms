import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.deps import CurrentUser, DbSession, require_role
from app.exceptions import NotFoundError, ValidationAppError
from app.models.catalog import CatalogItem
from app.models.enums import UserRole
from app.models.movements import StockMovement
from app.models.users import User
from app.schemas.catalog import CatalogItemCreate, CatalogItemResponse, CatalogItemUpdate
from app.schemas.common import Page
from app.schemas.stock import StockMovementResponse
from app.services.audit import write_audit

router = APIRouter(prefix="/catalog-items", tags=["catalog"])


@router.get("", response_model=Page[CatalogItemResponse])
async def list_catalog_items(
    db: DbSession,
    user: CurrentUser,
    q: str | None = None,
    vendor: uuid.UUID | None = None,
    category: uuid.UUID | None = None,
    is_serialized: bool | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> Any:
    page_size = min(page_size, 200)
    filters = []
    if q:
        filters.append(
            CatalogItem.part_number.ilike(f"%{q}%") | CatalogItem.name.ilike(f"%{q}%")
        )
    if vendor:
        filters.append(CatalogItem.vendor_id == vendor)
    if category:
        filters.append(CatalogItem.category_id == category)
    if is_serialized is not None:
        filters.append(CatalogItem.is_serialized == is_serialized)
    if is_active is not None:
        filters.append(CatalogItem.is_active == is_active)

    total = (
        await db.execute(select(func.count()).select_from(CatalogItem).where(*filters))
    ).scalar_one()
    stmt = (
        select(CatalogItem).where(*filters).offset((page - 1) * page_size).limit(page_size)
    )
    items = (await db.execute(stmt)).scalars().all()
    return Page(items=list(items), total=total, page=page, page_size=page_size)


@router.post("", response_model=CatalogItemResponse, status_code=201)
async def create_catalog_item(
    payload: CatalogItemCreate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    item = CatalogItem(**payload.model_dump())
    db.add(item)
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="catalog_item.create",
        entity_type="catalog_item",
        entity_id=str(item.id),
        details=payload.model_dump(mode="json"),
    )
    return item


@router.get("/{item_id}", response_model=CatalogItemResponse)
async def get_catalog_item(item_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Any:
    item = await db.get(CatalogItem, item_id)
    if item is None:
        raise NotFoundError("Articolo non trovato.", details={"id": str(item_id)})
    return item


@router.get("/{item_id}/movements", response_model=list[StockMovementResponse])
async def get_catalog_item_movements(
    item_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Any:
    result = await db.execute(
        select(StockMovement)
        .where(StockMovement.catalog_item_id == item_id)
        .order_by(StockMovement.occurred_at.desc())
        .limit(20)
    )
    return result.scalars().all()


@router.patch("/{item_id}", response_model=CatalogItemResponse)
async def update_catalog_item(
    item_id: uuid.UUID,
    payload: CatalogItemUpdate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    item = await db.get(CatalogItem, item_id)
    if item is None:
        raise NotFoundError("Articolo non trovato.", details={"id": str(item_id)})
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(item, key, value)
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="catalog_item.update",
        entity_type="catalog_item",
        entity_id=str(item.id),
        details={"changed_fields": changes},
    )
    return item


@router.post("/{item_id}/deactivate", response_model=CatalogItemResponse)
async def deactivate_catalog_item(
    item_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    item = await db.get(CatalogItem, item_id)
    if item is None:
        raise NotFoundError("Articolo non trovato.", details={"id": str(item_id)})
    item.is_active = False
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="catalog_item.deactivate",
        entity_type="catalog_item",
        entity_id=str(item.id),
        details={},
    )
    return item


@router.delete("/{item_id}", status_code=204)
async def delete_catalog_item(
    item_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> None:
    """Remove an article created by mistake.

    Mirrors the registries (see `generic_crud.build_registry_router`): possible
    only while nothing refers to it, and the database's own foreign keys are
    what decide. An article that has ever been received is part of the history
    of those pieces and can only be deactivated.
    """
    item = await db.get(CatalogItem, item_id)
    if item is None:
        raise NotFoundError("Articolo non trovato.", details={"id": str(item_id)})

    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="catalog_item.delete",
        entity_type="catalog_item",
        entity_id=str(item_id),
        details={"part_number": item.part_number},
    )
    try:
        await db.delete(item)
        await db.flush()
    except IntegrityError as exc:
        raise ValidationAppError(
            "Non è possibile eliminare questo articolo: è già usato da merce o "
            "movimenti registrati. Puoi disattivarlo, così sparisce dai menù "
            "senza toccare lo storico.",
            details={"id": str(item_id)},
        ) from exc
