import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db import AsyncSessionLocal


def pytest_sessionstart(session: pytest.Session) -> None:
    """Si rifiuta di partire se il database non è quello di prova.

    Il Makefile punta al posto giusto, ma il Makefile è una convenzione: chi
    lancia `pytest` a mano dentro il container — che è la cosa più naturale
    del mondo mentre si lavora — finiva sul database di produzione. Questo
    controllo è la garanzia, il Makefile è solo la comodità.

    Il danno non è ipotetico: i test creano utenti e `login()` fa `commit`
    per progetto (§6.4), quindi nessun rollback li ripulisce e restano nel
    database su cui hanno girato. Il giorno in cui un test tocca
    `stock_movements`, che è append-only, quella scrittura non si toglie
    più.
    """
    nome = get_settings().database_url.rsplit("/", 1)[-1].split("?")[0]
    if not nome.endswith("_test"):
        pytest.exit(
            f"I test girerebbero su «{nome}», che non è un database di prova.\n"
            "Usa 'make test' (prepara e usa netstock_test), oppure passa\n"
            "DATABASE_URL e MIGRATE_DATABASE_URL a un database che finisce per _test.",
            returncode=2,
        )


@pytest.fixture
async def app_db_session():
    """Session using the runtime `netstock_app` role (limited privileges)."""
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def superuser_connection():
    """Connection using the migration (superuser) role.

    Needed specifically to prove the append-only *trigger* blocks mutation
    even for a role that has table-level UPDATE/DELETE privileges — the
    `netstock_app` role never has those privileges at all (§4.2 REVOKE), so
    testing through it would only prove the privilege barrier, not the
    trigger barrier.
    """
    settings = get_settings()
    engine = create_async_engine(settings.migrate_database_url or settings.database_url)
    async with engine.connect() as connection:
        yield connection
        await connection.rollback()
    await engine.dispose()
