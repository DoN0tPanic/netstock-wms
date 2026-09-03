from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.config import get_settings
from app.deps import SESSION_COOKIE_NAME, CurrentUser, DbSession, get_client_ip
from app.exceptions import LockedOutError, UnauthorizedError, ValidationAppError
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.auth import ChangePasswordRequest, CurrentUserResponse, LoginRequest
from app.services.audit import write_audit
from app.services.auth.blocklist import is_common_password
from app.services.auth.local import LocalAuthProvider
from app.services.auth.password import hash_password, verify_password
from app.services.auth.session import create_session, revoke_session

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

_ROLE_PERMISSIONS: dict[UserRole, dict[str, bool]] = {
    UserRole.viewer: {"can_write": False, "can_administer": False},
    UserRole.operator: {"can_write": True, "can_administer": False},
    UserRole.admin: {"can_write": True, "can_administer": True},
}


@router.post("/login", response_model=CurrentUserResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> CurrentUserResponse:
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()

    generic_error = UnauthorizedError("Nome utente o password non corretti.")

    if user is not None and user.locked_until and user.locked_until > datetime.now(UTC):
        await write_audit(
            db,
            actor=None,
            actor_username=payload.username,
            action="auth.login_blocked",
            details={},
            ip_address=client_ip,
            user_agent=user_agent,
        )
        await db.commit()
        raise LockedOutError(
            "Account temporaneamente bloccato per troppi tentativi falliti. Riprovare più tardi."
        )

    provider = LocalAuthProvider(db)
    auth_result = await provider.authenticate(payload.username, payload.password)

    if not auth_result.success or user is None:
        if user is not None:
            user.failed_attempts += 1
            if user.failed_attempts >= settings.login_lockout_attempts:
                user.locked_until = datetime.now(UTC) + timedelta(
                    minutes=settings.login_lockout_minutes
                )
        await write_audit(
            db,
            actor=None,
            actor_username=payload.username,
            action="auth.login_failed",
            details={},
            ip_address=client_ip,
            user_agent=user_agent,
        )
        # Il tentativo fallito va reso definitivo **prima** di sollevare: la
        # sessione di richiesta annulla tutto su qualunque eccezione (§6.4),
        # quindi il conteggio e la riga di audit venivano scritti e subito
        # buttati via. Conseguenze misurate: il blocco dopo N tentativi non è
        # mai scattato — `failed_attempts` restava a zero — e il registro di
        # sicurezza conservava soltanto gli accessi riusciti, che è la metà
        # meno utile delle due.
        await db.commit()
        raise generic_error

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)

    token = await create_session(db, user, ip_address=client_ip, user_agent=user_agent)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.session_duration_hours * 3600,
    )

    # L'accesso riuscito non va in `audit_log`. È l'evento più frequente del
    # sistema — una riga per ogni mattina di ogni persona, per sempre — in una
    # tabella che per §4.2 nessuno può ripulire: cresce e basta. E non è
    # nemmeno l'unico posto dove è scritto: `sessions` conserva inizio, IP e
    # user agent di ogni accesso, e `users.last_login_at` l'ultimo: due
    # tabelle che si possono ripulire. Restano in audit i tentativi
    # falliti e i blocchi (§6.4), che sono pochi e sono quelli che si vanno a
    # cercare davvero dopo un incidente.

    return CurrentUserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        must_change_password=user.must_change_password,
        permissions=_ROLE_PERMISSIONS[user.role],
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: DbSession, user: CurrentUser) -> None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        await revoke_session(db, token)
    response.delete_cookie(SESSION_COOKIE_NAME)
    # Nemmeno l'uscita finisce in audit: `sessions.revoked_at` la registra già,
    # ed è la gemella dell'accesso qui sopra. `user` resta nella firma perché è
    # la dipendenza che pretende una sessione valida, non un residuo.


@router.get("/me", response_model=CurrentUserResponse)
async def me(user: CurrentUser) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        must_change_password=user.must_change_password,
        permissions=_ROLE_PERMISSIONS[user.role],
    )


@router.post("/change-password", status_code=204)
async def change_password(
    payload: ChangePasswordRequest, db: DbSession, user: CurrentUser
) -> None:
    if user.password_hash is None or not verify_password(
        payload.current_password, user.password_hash
    ):
        raise UnauthorizedError("Password attuale non corretta.")
    if len(payload.new_password) < settings.password_min_length:
        raise ValidationAppError(
            f"La nuova password deve avere almeno {settings.password_min_length} caratteri."
        )
    if is_common_password(payload.new_password):
        raise ValidationAppError("La password scelta è troppo comune, sceglierne un'altra.")

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False

    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="auth.change_password",
        details={},
    )
