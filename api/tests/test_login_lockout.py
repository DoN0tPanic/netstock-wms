"""Il blocco dopo troppi tentativi, e la traccia che ne resta.

Regressione con conseguenze di sicurezza: il conteggio dei tentativi falliti e
la riga di audit venivano scritti nella sessione della richiesta, che viene
**annullata su qualunque eccezione** (§6.4) — e la risposta 401 è un'eccezione.
`failed_attempts` restava quindi a zero per sempre: il blocco documentato non
è mai scattato, e il registro di sicurezza conservava soltanto gli accessi
riusciti, cioè la metà meno interessante delle due.

Il difetto era invisibile leggendo il codice, che le scritture le fa: si vede
solo guardando la tabella dopo. Per questo il test passa dall'endpoint vero e
poi controlla il database, invece di verificare che una funzione sia stata
chiamata.

L'utente di prova viene creato e rimosso qui: il gestore fa `commit`, quindi
un rollback della sessione non basterebbe a ripulire.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.v1.auth import login
from app.config import get_settings
from app.exceptions import LockedOutError, UnauthorizedError
from app.models.audit import AuditLog
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.auth import LoginRequest
from app.services.auth.password import hash_password

settings = get_settings()
PASSWORD = "Prova-Blocco-2026!"


class _RispostaFinta:
    def set_cookie(self, **_kwargs) -> None:
        pass


class _RichiestaFinta:
    client = type("Client", (), {"host": "203.0.113.9"})()
    headers: dict[str, str] = {}


@pytest.fixture
async def utente_di_prova(app_db_session):
    username = f"prova-blocco-{uuid.uuid4().hex[:8]}"
    utente = User(
        username=username,
        full_name="Utente di prova",
        role=UserRole.viewer,
        password_hash=hash_password(PASSWORD),
        is_active=True,
        must_change_password=False,
    )
    app_db_session.add(utente)
    await app_db_session.commit()
    yield utente
    # Da quando l'accesso riuscito non scrive più in audit, qui non resta
    # niente che punti a questo utente e la cancellazione riesce. Il ripiego
    # sulla disattivazione resta per il caso in cui una riga ci sia comunque:
    # il registro è append-only, e nessuno deve poter far sparire l'autore di
    # un'azione registrata.
    try:
        await app_db_session.execute(delete(User).where(User.username == username))
        await app_db_session.commit()
    except IntegrityError:
        await app_db_session.rollback()
        rimasto = await _ricarica(app_db_session, username)
        rimasto.is_active = False
        await app_db_session.commit()


async def _tenta(db, username: str, password: str):
    return await login(
        payload=LoginRequest(username=username, password=password),
        request=_RichiestaFinta(),  # type: ignore[arg-type]
        response=_RispostaFinta(),  # type: ignore[arg-type]
        db=db,
    )


async def _ricarica(db, username: str) -> User:
    db.expire_all()
    return (await db.execute(select(User).where(User.username == username))).scalar_one()


@pytest.mark.asyncio
async def test_un_tentativo_fallito_viene_contato(app_db_session, utente_di_prova):
    with pytest.raises(UnauthorizedError):
        await _tenta(app_db_session, utente_di_prova.username, "password-sbagliata")

    utente = await _ricarica(app_db_session, utente_di_prova.username)
    assert utente.failed_attempts == 1, "il conteggio non è sopravvissuto alla risposta 401"


@pytest.mark.asyncio
async def test_il_tentativo_fallito_finisce_nel_registro(app_db_session, utente_di_prova):
    with pytest.raises(UnauthorizedError):
        await _tenta(app_db_session, utente_di_prova.username, "password-sbagliata")

    quante = (
        await app_db_session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "auth.login_failed",
                AuditLog.actor_username == utente_di_prova.username,
            )
        )
    ).scalar_one()
    assert quante == 1, "un registro di sicurezza che annota solo i successi non serve"


@pytest.mark.asyncio
async def test_dopo_la_soglia_l_account_si_blocca(app_db_session, utente_di_prova):
    for _ in range(settings.login_lockout_attempts):
        with pytest.raises(UnauthorizedError):
            await _tenta(app_db_session, utente_di_prova.username, "password-sbagliata")

    utente = await _ricarica(app_db_session, utente_di_prova.username)
    assert utente.locked_until is not None
    assert utente.locked_until > datetime.now(UTC)


@pytest.mark.asyncio
async def test_mentre_e_bloccato_nemmeno_la_password_giusta_entra(
    app_db_session, utente_di_prova
):
    for _ in range(settings.login_lockout_attempts):
        with pytest.raises(UnauthorizedError):
            await _tenta(app_db_session, utente_di_prova.username, "password-sbagliata")

    # È il punto del blocco: se la password corretta passasse lo stesso, chi
    # tira a indovinare avrebbe soltanto perso qualche secondo.
    with pytest.raises(LockedOutError):
        await _tenta(app_db_session, utente_di_prova.username, PASSWORD)


@pytest.mark.asyncio
async def test_l_accesso_riuscito_non_scrive_nel_registro(app_db_session, utente_di_prova):
    """L'evento più frequente del sistema non va in una tabella che non si pota.

    Una riga per ogni accesso di ogni persona, per sempre, in una tabella che
    per §4.2 nessuno può ripulire. Chi è entrato e quando resta scritto in
    `sessions` e in `users.last_login_at`, che invece si possono ripulire.
    """
    await _tenta(app_db_session, utente_di_prova.username, PASSWORD)

    quante = (
        await app_db_session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.actor_username == utente_di_prova.username)
        )
    ).scalar_one()
    assert quante == 0

    utente = await _ricarica(app_db_session, utente_di_prova.username)
    assert utente.last_login_at is not None, "senza audit, l'ora dell'accesso deve restare qui"


@pytest.mark.asyncio
async def test_un_accesso_riuscito_azzera_il_conteggio(app_db_session, utente_di_prova):
    with pytest.raises(UnauthorizedError):
        await _tenta(app_db_session, utente_di_prova.username, "password-sbagliata")
    await _tenta(app_db_session, utente_di_prova.username, PASSWORD)

    utente = await _ricarica(app_db_session, utente_di_prova.username)
    assert utente.failed_attempts == 0
    assert utente.locked_until is None
