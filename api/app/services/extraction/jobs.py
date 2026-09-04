"""Registro in memoria delle analisi in corso.

L'analisi col modello dura da pochi secondi con una GPU a diversi minuti su
sola CPU (misurato sulla stessa bolla, con lo stesso identico risultato). Una
richiesta HTTP bloccante non regge il secondo caso, quindi la lettura torna
subito col risultato deterministico e l'analisi prosegue in sottofondo.

I risultati stanno **solo in memoria**, di proposito: §7.5 dice che il testo
OCR non tocca mai un volume persistente e non entra nel database. Un riavvio
dell'API perde le analisi in corso, ed è il comportamento voluto — si rifà la
foto, non si conserva il contenuto di una bolla per comodità.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

logger = structlog.get_logger("netstock.extraction.jobs")

JobStatus = Literal["running", "done", "failed"]

# Quanto resta disponibile un risultato dopo essere stato prodotto. Deve
# coprire il caso peggiore su CPU più il tempo che l'operatore impiega a
# tornare sullo schermo.
_TTL_SECONDS = 30 * 60
_MAX_JOBS = 64

# Ollama serve una richiesta per volta (OLLAMA_NUM_PARALLEL=1): lanciarne dieci
# insieme non le rende più veloci, le mette solo in coda occupando memoria.
_MAX_CONCURRENT = 2


@dataclass
class Job:
    id: str
    status: JobStatus = "running"
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None


_jobs: dict[str, Job] = {}
_lock = asyncio.Lock()
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
_tasks: set[asyncio.Task] = set()


def _purge(now: float) -> None:
    expired = [
        job_id
        for job_id, job in _jobs.items()
        if job.finished_at is not None and now - job.finished_at > _TTL_SECONDS
    ]
    for job_id in expired:
        del _jobs[job_id]

    # Rete di sicurezza: se qualcosa resta appeso in "running" il registro non
    # deve crescere all'infinito. Si scartano i più vecchi.
    if len(_jobs) > _MAX_JOBS:
        for job_id, _ in sorted(_jobs.items(), key=lambda kv: kv[1].created_at)[
            : len(_jobs) - _MAX_JOBS
        ]:
            del _jobs[job_id]


async def submit(coro_factory) -> str:
    """Registra un lavoro e lo avvia in sottofondo. Torna il suo identificativo."""
    job_id = str(uuid.uuid4())
    job = Job(id=job_id)
    async with _lock:
        _purge(time.monotonic())
        _jobs[job_id] = job

    async def runner() -> None:
        try:
            async with _semaphore:
                job.result = await coro_factory()
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 — un'analisi fallita non deve
            # abbattere il processo: l'operatore ha già il risultato deterministico.
            job.status = "failed"
            job.error = str(exc)
            logger.warning("extraction_job_failed", job_id=job_id, error=str(exc))
        finally:
            job.finished_at = time.monotonic()

    task = asyncio.create_task(runner())
    # Senza tenere un riferimento forte, il garbage collector può raccogliere il
    # task a metà e l'analisi sparisce senza lasciare traccia.
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job_id


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def reset() -> None:
    """Solo per i test."""
    _jobs.clear()
    _tasks.clear()
