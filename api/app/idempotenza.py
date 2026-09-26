"""Operazioni di magazzino che si possono ripetere senza registrarle due volte.

Il caso che conta: una ricezione parte, il server la registra, la risposta si
perde sulla rete. Chi è al banco vede un errore e preme di nuovo. Senza
questo, il secondo invio registrava un secondo carico — e il registro dei
movimenti per progetto non si cancella: si corregge solo con uno storno, se
qualcuno si accorge del doppio.

Il browser genera una chiave per ogni operazione e la rimanda uguale finché
l'operazione non è andata a buon fine. Qui la chiave si scrive nella stessa
transazione dei movimenti, **prima** di eseguirli:

- se un'altra richiesta con la stessa chiave è già in corso, PostgreSQL fa
  aspettare questa finché l'altra non ha finito; poi l'inserimento fallisce
  sul vincolo di unicità, e si restituisce la risposta data alla prima;
- se l'operazione fallisce, la transazione si annulla e la chiave con lei:
  un nuovo tentativo è libero di riprovare;
- se riesce, chiave e movimenti restano insieme. Non esiste un momento in cui
  l'operazione è registrata e la chiave no, nemmeno se il server si spegne.

Senza intestazione tutto funziona come prima: la chiave protegge chi la
manda, non obbliga chi non la manda.
"""

import hashlib
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictAppError, ValidationAppError
from app.models.idempotency import IdempotencyKey
from app.models.users import User

INTESTAZIONE = "Idempotency-Key"
LUNGHEZZA_MASSIMA = 200
# Una ripetizione arriva nel giro di secondi o minuti: una settimana è ampia,
# e dopo la chiave non protegge più niente.
CONSERVAZIONE = timedelta(days=7)


def _impronta(metodo: str, percorso: str, corpo: bytes) -> str:
    """La richiesta ridotta a un'impronta: stessa chiave, stessa operazione."""
    return hashlib.sha256(f"{metodo} {percorso}\n".encode() + corpo).hexdigest()


def _in_json(request: Request, risultato: Any) -> Any:
    """Il risultato come lo avrebbe serializzato FastAPI, per poterlo ridare."""
    rotta = request.scope.get("route")
    modello = getattr(rotta, "response_model", None)
    if modello is None:
        return TypeAdapter(Any).dump_python(risultato, mode="json")
    adattatore = TypeAdapter(modello)
    return adattatore.dump_python(
        adattatore.validate_python(risultato, from_attributes=True), mode="json"
    )


async def con_idempotenza(
    request: Request,
    db: AsyncSession,
    user: User,
    operazione: Callable[[], Awaitable[Any]],
) -> Any:
    chiave = (request.headers.get(INTESTAZIONE) or "").strip()
    if not chiave:
        return await operazione()
    if len(chiave) > LUNGHEZZA_MASSIMA:
        raise ValidationAppError(
            f"La chiave di idempotenza supera i {LUNGHEZZA_MASSIMA} caratteri."
        )

    utente = user.id
    impronta = _impronta(request.method, request.url.path, await request.body())
    riga = IdempotencyKey(
        user_id=utente, key=chiave, route=request.url.path, request_hash=impronta
    )
    # La chiave si prenota in un punto di ripristino: se è già presa, si
    # annulla soltanto la prenotazione, non tutto quello che la richiesta
    # avesse già fatto. Annullare l'intera transazione funzionava finché la
    # richiesta non faceva nient'altro prima — una garanzia appesa a un'abitudine.
    punto = await db.begin_nested()
    try:
        db.add(riga)
        await db.flush()
    except IntegrityError:
        await punto.rollback()
        return await _gia_eseguita(db, utente, chiave, impronta)
    await punto.commit()

    risultato = await operazione()
    rotta = request.scope.get("route")
    riga.status_code = getattr(rotta, "status_code", None) or 200
    riga.response = _in_json(request, risultato)
    await db.flush()
    return risultato


async def _gia_eseguita(
    db: AsyncSession, utente: Any, chiave: str, impronta: str
) -> JSONResponse:
    esistente = await db.get(IdempotencyKey, (utente, chiave))
    if esistente is None or esistente.response is None:
        # Non dovrebbe succedere: una riga confermata ha sempre la risposta,
        # perché si scrive nella stessa transazione. Se succede, meglio dire
        # di riprovare che eseguire due volte.
        raise ConflictAppError(
            "Questa operazione è ancora in corso: aspetta un attimo e ricarica la pagina."
        )
    if esistente.request_hash != impronta:
        # Succede quando un invio precedente è andato a buon fine ma la
        # risposta si è persa, e intanto il modulo è stato cambiato. Rifarlo
        # alla cieca sarebbe il doppione che questa chiave esiste a impedire.
        raise ValidationAppError(
            "Un invio precedente di questa operazione risulta già registrato, con "
            "dati diversi. Ricarica la pagina e controlla il magazzino prima di "
            "ripeterla.",
            details={"chiave": chiave},
        )
    return JSONResponse(
        content=esistente.response,
        status_code=esistente.status_code or 200,
        headers={"Idempotent-Replayed": "true"},
    )


async def elimina_chiavi_scadute(db: AsyncSession) -> int:
    """Toglie le chiavi più vecchie della conservazione; restituisce quante."""
    risultato = await db.execute(
        # La durata come intervallo, e con il tipo dichiarato. Come testo il
        # driver la rifiuta; senza tipo PostgreSQL la legge come una data, e
        # `now() - data` è un intervallo da confrontare con una data. In tutti
        # e due i casi la pulizia sarebbe fallita ogni notte, in silenzio.
        text("DELETE FROM idempotency_keys WHERE created_at < now() - CAST(:finestra AS interval)"),
        {"finestra": CONSERVAZIONE},
    )
    return risultato.rowcount or 0
