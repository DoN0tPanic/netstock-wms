import uuid

from pydantic import BaseModel, Field

from app.models.enums import UserRole
from app.schemas.common import OrmModel


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)


class CurrentUserResponse(OrmModel):
    id: uuid.UUID
    username: str
    full_name: str
    email: str | None
    role: UserRole
    must_change_password: bool
    permissions: dict[str, bool]
