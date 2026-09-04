import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager

import httpx
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.v1 import api_router
from app.api.v1.health import router as health_router
from app.config import get_settings
from app.db import AsyncSessionLocal
from app.exceptions import AppError
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.services import ai_config
from app.services.audit import write_audit
from app.services.reservations import expire_reservations

settings = get_settings()


def _configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=getattr(logging, settings.log_level)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def _job_expire_reservations() -> None:
    async with AsyncSessionLocal() as db:
        count = await expire_reservations(db)
        await db.commit()
        if count:
            structlog.get_logger("netstock.jobs").info("reservations_expired", count=count)


async def _job_reconcile_stock() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT count(*) FROM v_reconciliation_errors"))
        error_count = result.scalar_one()
        logger = structlog.get_logger("netstock.jobs")
        if error_count:
            logger.error("stock_reconciliation_failed", error_count=error_count)
            await write_audit(
                db,
                actor=None,
                actor_username="system",
                action="stock.reconciliation_failed",
                details={"error_count": error_count},
            )
            await db.commit()
        else:
            logger.info("stock_reconciliation_ok")


# Qui c'era `_job_warranty_alerts`: ogni notte contava le garanzie in scadenza
# e scriveva una riga di structlog dentro il container, i cui log ruotano ogni
# 10 MB. Nessuno l'ha mai letta, e non c'era modo che qualcuno la leggesse.
# Copertura finta, che è peggio di niente perché sembra fatta: chi guardava
# l'elenco dei job vedeva che gli avvisi «c'erano».
#
# Le garanzie in scadenza a 60 giorni la dashboard le mostra già, con le righe
# invece del solo conteggio (`GET /dashboard`). Quella è l'unica via per cui
# l'informazione arriva davvero a una persona, e adesso è anche l'unica che
# esiste. Se un giorno serve un avviso che raggiunge chi non sta guardando lo
# schermo — una mail, un webhook — quello è un canale da costruire, non una
# riga di log da ripristinare.


async def _job_purge_sessions() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM sessions WHERE expires_at < now() - interval '30 days'")
        )
        await db.commit()


async def _job_purge_extraction_runs() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "DELETE FROM extraction_runs WHERE ts < "
                "now() - make_interval(days => :days)"
            ),
            {"days": settings.extraction_log_retention_days},
        )
        await db.commit()


async def _job_purge_audit_log() -> None:
    """Toglie dal registro di controllo le righe più vecchie della conservazione.

    Gira con la connessione del **proprietario**, non con quella
    dell'applicazione: al ruolo applicativo il permesso di cancellare da
    `audit_log` resta negato, e questa è la prima delle due barriere. La
    seconda è il trigger, che accetta la cancellazione solo se la sessione
    dichiara la pulizia e solo per righe già scadute (§0008) — quindi anche
    da qui non si può cancellare una riga di ieri.

    La pulizia si registra nel registro stesso: quante righe sono sparite e
    fino a quando. Quella riga scadrà a sua volta fra un anno, ed è giusto
    così — dice qualcosa su un periodo che a quel punto non c'è più.
    """
    logger = structlog.get_logger("netstock.jobs")
    if settings.migrate_database_url is None:
        logger.warning("pulizia_audit_saltata", motivo="manca la connessione del proprietario")
        return
    motore = create_async_engine(settings.migrate_database_url, pool_pre_ping=True)
    try:
        async with motore.begin() as conn:
            # `SET LOCAL` vale per questa transazione soltanto: fuori di qui la
            # tabella torna intoccabile senza bisogno di ricordarsi di
            # richiudere niente, nemmeno se qualcosa va storto a metà.
            # `set_config(..., true)` e non `SET LOCAL`: la seconda forma non
            # accetta parametri, e concatenare la finestra nella stringa SQL
            # sarebbe il modo di scriverci dentro qualcos'altro. Vale per la
            # transazione, come `SET LOCAL`.
            await conn.execute(
                text("SELECT set_config('netstock.pulizia_audit', 'in-corso', true)")
            )
            await conn.execute(
                text("SELECT set_config('netstock.audit_retention', :finestra, true)"),
                {"finestra": f"{settings.audit_retention_days} days"},
            )
            esito = await conn.execute(
                text(
                    "DELETE FROM audit_log WHERE ts < "
                    "now() - make_interval(days => :giorni)"
                ),
                {"giorni": settings.audit_retention_days},
            )
            tolte = esito.rowcount or 0
            if tolte:
                await conn.execute(
                    text(
                        "INSERT INTO audit_log (actor_username, action, entity_type, details) "
                        "VALUES ('sistema', 'audit.prune', 'audit_log', CAST(:dettagli AS JSONB))"
                    ),
                    {
                        "dettagli": json.dumps(
                            {"righe": tolte, "conservazione_giorni": settings.audit_retention_days}
                        )
                    },
                )
        if tolte:
            logger.info("pulizia_audit", righe=tolte, giorni=settings.audit_retention_days)
    finally:
        await motore.dispose()


async def _warm_up_extraction_model() -> None:
    """Carica il modello in memoria appena l'API è su.

    La prima richiesta dopo il caricamento paga l'inizializzazione del runtime
    — misurata in decine di secondi anche con la GPU. Pagarla qui, mentre non
    c'è nessuno che aspetta, vuol dire che la prima bolla della giornata è
    veloce quanto le altre. Se Ollama non c'è (installazione senza AI) fallisce
    in silenzio: non è un servizio obbligatorio.
    """
    if not settings.extract_enabled:
        return
    # Il modello da scaldare è quello scelto adesso, non quello scritto nel
    # file di configurazione: si può cambiare dalle Impostazioni, e riscaldare
    # quello sbagliato lascerebbe fredda la prima lettura vera.
    modello_scelto = await ai_config.modello()
    try:
        async with httpx.AsyncClient(
            base_url=settings.ollama_base_url, timeout=httpx.Timeout(600.0, connect=5.0)
        ) as client:
            response = await client.post(
                "/api/generate",
                json={
                    "model": modello_scelto,
                    "prompt": "ok",
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": 1},
                },
            )
            response.raise_for_status()
        structlog.get_logger("netstock.extraction").info(
            "extraction_model_warm", model=modello_scelto
        )
    except Exception as exc:  # noqa: BLE001
        structlog.get_logger("netstock.extraction").info(
            "extraction_model_unavailable", error=str(exc)
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    scheduler.add_job(_job_expire_reservations, "cron", hour=2, minute=0)
    scheduler.add_job(_job_reconcile_stock, "cron", hour=2, minute=15)
    scheduler.add_job(_job_purge_sessions, "cron", hour=3, minute=0)
    scheduler.add_job(_job_purge_extraction_runs, "cron", hour=3, minute=5)
    scheduler.add_job(_job_purge_audit_log, "cron", hour=3, minute=10)
    scheduler.start()
    app.state.scheduler = scheduler
    warmup = asyncio.create_task(_warm_up_extraction_model())
    yield
    warmup.cancel()
    scheduler.shutdown(wait=False)


app = FastAPI(title="NetStock API", version="1.0.0", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIDMiddleware)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {"code": exc.code, "message": exc.message, "details": exc.details}
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Dati non validi nella richiesta.",
                "details": {"errors": exc.errors()},
            }
        },
    )


app.include_router(health_router)
app.include_router(api_router, prefix="/api/v1")
