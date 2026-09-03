import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.users import Session as SessionModel
from app.models.users import User

settings = get_settings()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_session(
    db: AsyncSession, user: User, ip_address: str | None, user_agent: str | None
) -> str:
    token = secrets.token_urlsafe(32)
    session = SessionModel(
        user_id=user.id,
        token_hash=_hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.session_duration_hours),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)
    await db.flush()
    return token


async def get_session_user(db: AsyncSession, token: str) -> User | None:
    token_hash = _hash_token(token)
    now = datetime.now(UTC)
    result = await db.execute(
        select(SessionModel).where(
            SessionModel.token_hash == token_hash,
            SessionModel.revoked_at.is_(None),
            SessionModel.expires_at > now,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None

    session.expires_at = now + timedelta(hours=settings.session_duration_hours)

    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


async def revoke_session(db: AsyncSession, token: str) -> None:
    token_hash = _hash_token(token)
    result = await db.execute(select(SessionModel).where(SessionModel.token_hash == token_hash))
    session = result.scalar_one_or_none()
    if session is not None:
        session.revoked_at = datetime.now(UTC)
