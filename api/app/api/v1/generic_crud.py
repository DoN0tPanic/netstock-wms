import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.deps import CurrentUser, DbSession, require_role
from app.exceptions import NotFoundError, ValidationAppError
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.common import Page
from app.services.audit import write_audit

ModelT = TypeVar("ModelT", bound=DeclarativeBase)
CreateT = TypeVar("CreateT", bound=BaseModel)
UpdateT = TypeVar("UpdateT", bound=BaseModel)
ResponseT = TypeVar("ResponseT", bound=BaseModel)


def build_registry_router(
    *,
    prefix: str,
    tag: str,
    model: type[ModelT],
    create_schema: type[CreateT],
    update_schema: type[UpdateT],
    response_schema: type[ResponseT],
    search_fields: list[str],
    entity_name: str,
    supports_deactivate: bool = True,
    deactivate_guard: Callable[[AsyncSession, Any], Awaitable[None]] | None = None,
    prepare_create: Callable[[AsyncSession, dict[str, Any]], Awaitable[dict[str, Any]]]
    | None = None,
) -> APIRouter:
    """Builds the identical CRUD router shared by vendors/categories/suppliers/
    locations (§6.2: "schema CRUD identico").

    Retiring an entry that is already in use is a deactivation, which keeps the
    history readable. Outright DELETE exists only for entries nothing refers to
    yet — the typo you notice a minute after saving it.
    """
    router = APIRouter(prefix=prefix, tags=[tag])

    @router.get("", response_model=Page[response_schema])
    async def list_items(
        db: DbSession,
        user: CurrentUser,
        q: str | None = None,
        is_active: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Any:
        page_size = min(page_size, 200)
        filters = []
        if q:
            from sqlalchemy import or_

            columns = [getattr(model, field) for field in search_fields]
            filters.append(or_(*[col.ilike(f"%{q}%") for col in columns]))
        if is_active is not None and hasattr(model, "is_active"):
            filters.append(model.is_active == is_active)

        total = (
            await db.execute(select(func.count()).select_from(model).where(*filters))
        ).scalar_one()

        stmt = select(model).where(*filters).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(stmt)
        items: Sequence[Any] = result.scalars().all()
        return Page(items=list(items), total=total, page=page, page_size=page_size)

    @router.post("", response_model=response_schema, status_code=201)
    async def create_item(
        payload: create_schema,  # type: ignore[valid-type]
        db: DbSession,
        user: User = Depends(require_role(UserRole.operator)),
    ) -> Any:
        valori = payload.model_dump()
        # L'unico punto in cui questo CRUD identico si lascia completare: le
        # ubicazioni ricavano il codice dal nome quando non è stato scritto.
        if prepare_create is not None:
            valori = await prepare_create(db, valori)
        instance = model(**valori)
        db.add(instance)
        await db.flush()
        await write_audit(
            db,
            actor=user,
            actor_username=user.username,
            action=f"{entity_name}.create",
            entity_type=entity_name,
            entity_id=str(instance.id),
            details={**payload.model_dump(mode="json"), "code": valori.get("code")},
        )
        return instance

    @router.get("/{item_id}", response_model=response_schema)
    async def get_item(item_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Any:
        instance = await db.get(model, item_id)
        if instance is None:
            raise NotFoundError(f"{entity_name} non trovato.", details={"id": str(item_id)})
        return instance

    @router.patch("/{item_id}", response_model=response_schema)
    async def update_item(
        item_id: uuid.UUID,
        payload: update_schema,  # type: ignore[valid-type]
        db: DbSession,
        user: User = Depends(require_role(UserRole.operator)),
    ) -> Any:
        instance = await db.get(model, item_id)
        if instance is None:
            raise NotFoundError(f"{entity_name} non trovato.", details={"id": str(item_id)})
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(instance, key, value)
        await db.flush()
        await write_audit(
            db,
            actor=user,
            actor_username=user.username,
            action=f"{entity_name}.update",
            entity_type=entity_name,
            entity_id=str(instance.id),
            details={"changed_fields": changes},
        )
        return instance

    if supports_deactivate:

        @router.post("/{item_id}/deactivate", response_model=response_schema)
        async def deactivate_item(
            item_id: uuid.UUID,
            db: DbSession,
            user: User = Depends(require_role(UserRole.admin)),
        ) -> Any:
            instance = await db.get(model, item_id)
            if instance is None:
                raise NotFoundError(f"{entity_name} non trovato.", details={"id": str(item_id)})
            if deactivate_guard is not None:
                await deactivate_guard(db, instance)
            instance.is_active = False
            await db.flush()
            await write_audit(
                db,
                actor=user,
                actor_username=user.username,
                action=f"{entity_name}.deactivate",
                entity_type=entity_name,
                entity_id=str(instance.id),
                details={},
            )
            return instance

    @router.delete("/{item_id}", status_code=204)
    async def delete_item(
        item_id: uuid.UUID,
        db: DbSession,
        user: User = Depends(require_role(UserRole.admin)),
    ) -> None:
        """Remove an entry created by mistake.

        Only possible while nothing refers to it. Rather than enumerating every
        table that might point here — and forgetting one as the schema grows —
        the delete is attempted and the database's own foreign keys decide:
        whatever still references the row makes it fail, and that is turned
        into a plain explanation instead of a 500.
        """
        instance = await db.get(model, item_id)
        if instance is None:
            raise NotFoundError(f"{entity_name} non trovato.", details={"id": str(item_id)})

        label = getattr(instance, "code", None) or getattr(instance, "name", str(item_id))
        await write_audit(
            db,
            actor=user,
            actor_username=user.username,
            action=f"{entity_name}.delete",
            entity_type=entity_name,
            entity_id=str(item_id),
            details={"label": label},
        )
        try:
            await db.delete(instance)
            await db.flush()
        except IntegrityError as exc:
            raise ValidationAppError(
                "Non è possibile eliminare questa voce: è già usata da merce o "
                "movimenti registrati. Puoi disattivarla, così sparisce dai menù "
                "senza toccare lo storico.",
                details={"id": str(item_id)},
            ) from exc

    return router
