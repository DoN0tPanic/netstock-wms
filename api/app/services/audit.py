import datetime
import uuid
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.users import User

# Fields that must never reach the audit log, even inside `details`.
_FORBIDDEN_DETAIL_KEYS = {"password", "password_hash", "token", "session_token", "raw_ocr_text"}


def _json_safe(value: Any) -> Any:
    """Callers routinely build `details` from `payload.model_dump(exclude_unset=True)`
    (six endpoints do this as of writing), which keeps native Python types like
    `date`/`UUID`/`Decimal` — none of which the JSONB column's default JSON
    encoder can serialize. Coercing here, once, protects every caller instead
    of requiring each one to remember `mode="json"`.
    """
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _sanitize(details: dict[str, Any]) -> dict[str, Any]:
    return {k: _json_safe(v) for k, v in details.items() if k not in _FORBIDDEN_DETAIL_KEYS}


async def write_audit(
    db: AsyncSession,
    *,
    actor: User | None,
    actor_username: str,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    entry = AuditLog(
        actor_id=actor.id if actor is not None else None,
        actor_username=actor_username,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=_sanitize(details or {}),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(entry)
    await db.flush()
