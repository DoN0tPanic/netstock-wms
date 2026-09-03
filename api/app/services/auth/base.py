from dataclasses import dataclass
from typing import Protocol

from app.models.enums import UserRole


@dataclass(frozen=True)
class UserInfo:
    username: str
    full_name: str
    email: str | None
    role: UserRole


@dataclass(frozen=True)
class AuthResult:
    success: bool
    user_info: UserInfo | None
    failure_reason: str | None = None


class AuthProvider(Protocol):
    """Authentication abstraction.

    LocalAuthProvider is the only implementation in v1.0. LdapAuthProvider
    (phase 2, ADR required per §9.2) plugs in here without any change to the
    API endpoints — that is the correctness criterion for this abstraction.
    """

    async def authenticate(self, username: str, password: str) -> AuthResult: ...

    async def get_user_info(self, username: str) -> UserInfo | None: ...
