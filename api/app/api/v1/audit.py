from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.deps import DbSession, require_role
from app.models.audit import AuditLog
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.audit import AuditLogResponse
from app.schemas.common import Page

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditLogResponse])
async def list_audit_log(
    db: DbSession,
    actor: str | None = None,
    action: str | None = None,
    entity: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    page_size = min(page_size, 200)
    filters = []
    if actor:
        filters.append(AuditLog.actor_username.ilike(f"%{actor}%"))
    if action:
        filters.append(AuditLog.action.ilike(f"%{action}%"))
    if entity:
        filters.append(AuditLog.entity_type == entity)
    if date_from:
        filters.append(AuditLog.ts >= date_from)
    if date_to:
        filters.append(AuditLog.ts <= date_to)

    total = (
        await db.execute(select(func.count()).select_from(AuditLog).where(*filters))
    ).scalar_one()
    stmt = (
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.ts.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = (await db.execute(stmt)).scalars().all()
    return Page(items=list(items), total=total, page=page, page_size=page_size)
