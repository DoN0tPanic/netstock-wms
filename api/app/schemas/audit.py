import uuid
from datetime import datetime
from typing import Any

from pydantic import IPvAnyAddress

from app.schemas.common import OrmModel


class AuditLogResponse(OrmModel):
    id: int
    ts: datetime
    actor_id: uuid.UUID | None
    actor_username: str
    action: str
    entity_type: str | None
    entity_id: str | None
    details: dict[str, Any]
    ip_address: IPvAnyAddress | None
    user_agent: str | None
