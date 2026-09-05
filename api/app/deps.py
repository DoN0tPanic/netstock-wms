from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Cookie, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.exceptions import ForbiddenError, UnauthorizedError
from app.models.enums import UserRole
from app.models.users import User
from app.services.auth.session import get_session_user

SESSION_COOKIE_NAME = "netstock_session"

DbSession = Annotated[AsyncSession, Depends(get_db)]

_ROLE_RANK: dict[UserRole, int] = {
    UserRole.viewer: 0,
    UserRole.operator: 1,
    UserRole.admin: 2,
}


async def get_current_user(
    db: DbSession,
    netstock_session: Annotated[str | None, Cookie()] = None,
) -> User:
    if netstock_session is None:
        raise UnauthorizedError("Sessione assente: effettuare il login.")
    user = await get_session_user(db, netstock_session)
    if user is None:
        raise UnauthorizedError("Sessione scaduta o non valida: effettuare nuovamente il login.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(
    minimum_role: UserRole,
) -> Callable[[User], Coroutine[Any, Any, User]]:
    async def _dependency(user: CurrentUser) -> User:
        if _ROLE_RANK[user.role] < _ROLE_RANK[minimum_role]:
            raise ForbiddenError(
                f"Permesso insufficiente: richiesto ruolo '{minimum_role.value}' o superiore."
            )
        return user

    # Il ruolo resta leggibile dall'esterno: serve a un test che passa in
    # rassegna le rotte e controlla che ognuna pretenda quello che deve.
    # Senza, l'unico modo di accorgersi di un guardiano mancante è provare
    # l'endpoint con un utente vero — ed è così che è saltato fuori che
    # `GET /settings` non ne aveva nessuno.
    _dependency.ruolo_minimo = minimum_role  # type: ignore[attr-defined]
    return _dependency


def get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-real-ip")
    if forwarded:
        return forwarded
    if request.client:
        return request.client.host
    return None
