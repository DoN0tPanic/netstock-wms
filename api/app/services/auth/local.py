from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User
from app.services.auth.base import AuthProvider, AuthResult, UserInfo
from app.services.auth.password import verify_password


class LocalAuthProvider(AuthProvider):
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def authenticate(self, username: str, password: str) -> AuthResult:
        user = await self._get_user(username)
        if user is None or user.password_hash is None:
            return AuthResult(success=False, user_info=None, failure_reason="invalid_credentials")
        if not verify_password(password, user.password_hash):
            return AuthResult(success=False, user_info=None, failure_reason="invalid_credentials")
        if not user.is_active:
            return AuthResult(success=False, user_info=None, failure_reason="inactive")
        return AuthResult(
            success=True,
            user_info=UserInfo(
                username=user.username,
                full_name=user.full_name,
                email=user.email,
                role=user.role,
            ),
        )

    async def get_user_info(self, username: str) -> UserInfo | None:
        user = await self._get_user(username)
        if user is None:
            return None
        return UserInfo(
            username=user.username, full_name=user.full_name, email=user.email, role=user.role
        )

    async def _get_user(self, username: str) -> User | None:
        result = await self._db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()
