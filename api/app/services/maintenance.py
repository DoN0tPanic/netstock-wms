"""Copia di sicurezza e ripristino dall'applicazione.

Perché passa da `pg_dump` e non da un'esportazione applicativa: un backup deve
riportare il database esattamente com'era — vincoli, trigger append-only,
sequenze, permessi del ruolo runtime. Un giro di SELECT e INSERT scritto qui
sarebbe una cosa diversa, che somiglia a un backup finché non serve.

**Il backup fatto da qui esce dalla macchina.** Non si aggiunge alla cartella
sul server — quella la riempie il timer notturno — ma arriva sul computer di
chi preme il pulsante. È voluto: la copia che serve il giorno in cui muore il
disco è quella che non sta su quel disco.

Il ripristino, all'opposto, accetta un file caricato: è il caso vero del
disastro, in cui l'unica copia rimasta è quella che qualcuno si era portato
via.
"""
import asyncio
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import structlog
from sqlalchemy.engine import make_url

from app.config import get_settings

CARTELLA_BACKUP = Path("/var/backups/netstock")
# Oltre questa soglia il file caricato non è un dump di questo magazzino: è
# un'altra cosa, e leggerla per intero prima di accorgersene costa memoria.
# Il limite vero lo mette Caddy (`request_body` nel Caddyfile): quando questa
# funzione parte, Starlette ha già ricevuto tutto il multipart. Questo qui è
# una rete di sicurezza per chi chiamasse l'API senza passare dal proxy.
LIMITE_RIPRISTINO = 2 * 1024 * 1024 * 1024
CONFERMA = "RIPRISTINA"
# Un pg_dump o un pg_restore che non finisce tiene occupata la connessione e
# il lock: meglio interromperlo che lasciarlo appeso.
TIMEOUT = 900

# Una sola operazione per volta. Due ripristini in parallelo, o un ripristino
# mentre si sta facendo la copia di sicurezza, si sovrappongono sulle stesse
# tabelle: quello che ne esce non è né la copia vecchia né quella nuova.
_serratura = asyncio.Lock()

_log = structlog.get_logger("netstock.manutenzione")


def occupato() -> bool:
    return _serratura.locked()


def serratura() -> asyncio.Lock:
    return _serratura


@dataclass
class Esito:
    ok: bool
    messaggio: str
    dettaglio: str = ""


def _ambiente_libpq(database: str | None = None) -> dict[str, str]:
    """Le variabili con cui `pg_dump` e `pg_restore` trovano il database.

    Si usa l'utenza delle migrazioni, non quella dell'applicazione: la seconda
    per progetto (§4.2) non possiede le tabelle e non ha i permessi per
    ricrearle, quindi produrrebbe un dump che non si può ripristinare.
    """
    impostazioni = get_settings()
    url = make_url(impostazioni.migrate_database_url or impostazioni.database_url)
    return {
        **os.environ,
        "PGHOST": url.host or "db",
        "PGPORT": str(url.port or 5432),
        "PGUSER": url.username or "netstock",
        "PGPASSWORD": url.password or "",
        # `database` serve solo alle prove, che lavorano su un database usa e
        # getta invece che su quello configurato: un test di ripristino
        # ricrea tutte le tabelle, e farlo sul database degli altri test
        # significa farli cadere a seconda dell'ordine.
        "PGDATABASE": database or url.database or "netstock",
    }


def _senza_segreti(testo: str) -> str:
    """Toglie la password del database da un testo destinato a uscire.

    `PGPASSWORD` non finisce in argv e gli strumenti non la stampano, ma
    questo testo è lo `stderr` di un programma esterno: si redige prima di
    farlo uscire, invece di fidarsi che non ci sia mai.
    """
    password = _ambiente_libpq()["PGPASSWORD"]
    return testo.replace(password, "***") if password else testo


async def _esegui(
    *comando: str, ingresso: bytes | None = None, database: str | None = None
) -> tuple[int, bytes, bytes]:
    processo = await asyncio.create_subprocess_exec(
        *comando,
        stdin=asyncio.subprocess.PIPE if ingresso is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_ambiente_libpq(database),
    )
    try:
        uscita, errori = await asyncio.wait_for(processo.communicate(ingresso), TIMEOUT)
    except TimeoutError:
        processo.kill()
        await processo.wait()
        return 1, b"", f"{comando[0]} non ha finito entro {TIMEOUT} secondi.".encode()
    return processo.returncode or 0, uscita, errori


def _errore(messaggio: str, errori: bytes, *, operazione: str) -> "Esito":
    """L'errore resta leggibile a chi amministra, ma passa dal registro.

    Nasconderlo dietro un identificativo, su un'installazione con un solo
    amministratore, vorrebbe dire mandarlo a leggere i log del container per
    sapere perché non è riuscito qualcosa che ha appena chiesto lui.
    """
    dettaglio = _senza_segreti(errori.decode(errors="replace"))[:2000]
    _log.error("manutenzione_fallita", operazione=operazione, dettaglio=dettaglio)
    return Esito(False, messaggio, dettaglio)


async def versione_client() -> str:
    codice, uscita, _ = await _esegui("pg_dump", "--version")
    return uscita.decode().strip() if codice == 0 else "non disponibile"


def copie_sul_server() -> list[dict[str, object]]:
    """Le copie che il timer notturno ha lasciato sul server.

    La cartella è montata in sola lettura: qui si guarda soltanto, e se non
    c'è (installazione senza timer, o percorso diverso) l'elenco è vuoto
    invece di essere un errore.
    """
    if not CARTELLA_BACKUP.is_dir():
        return []
    copie = []
    for sottocartella in ("daily", "monthly"):
        cartella = CARTELLA_BACKUP / sottocartella
        if not cartella.is_dir():
            continue
        for file in sorted(cartella.glob("*.dump"), reverse=True):
            info = file.stat()
            copie.append(
                {
                    "nome": file.name,
                    "gruppo": "giornaliera" if sottocartella == "daily" else "mensile",
                    "byte": info.st_size,
                    "quando": info.st_mtime,
                }
            )
    return copie


def spazio_disco() -> dict[str, int] | None:
    if not CARTELLA_BACKUP.is_dir():
        return None
    uso = shutil.disk_usage(CARTELLA_BACKUP)
    return {"totale": uso.total, "usato": uso.used, "libero": uso.free}


async def crea_dump(percorso: Path, database: str | None = None) -> Esito:
    """Un dump nel formato compresso di PostgreSQL, l'unico che `pg_restore`
    sa applicare selettivamente e che `backup.sh` produce già."""
    codice, _, errori = await _esegui(
        "pg_dump", "-Fc", "--no-owner", "-f", str(percorso), database=database
    )
    if codice != 0:
        return _errore("Non è stato possibile creare la copia.", errori, operazione="dump")
    return Esito(True, "Copia creata.")


async def indice_dump(percorso: Path) -> Esito:
    """`pg_restore --list` legge l'indice: se non lo legge, non è un dump.

    È il primo controllo del ripristino, e vale la pena farlo prima di toccare
    qualunque cosa: un file sbagliato viene rifiutato mentre il database è
    ancora intatto.
    """
    codice, uscita, errori = await _esegui("pg_restore", "--list", str(percorso))
    if codice != 0:
        return _errore(
            "Il file non è una copia di sicurezza leggibile.", errori, operazione="indice"
        )
    return Esito(True, "Copia leggibile.", uscita.decode(errors="replace"))


def revisione_nel_dump(indice: str) -> str | None:
    """Quale revisione di schema porta il dump.

    Serve a dire dopo il ripristino se lo schema tornerà indietro: un dump di
    tre mesi fa non conosce le colonne aggiunte da allora, e l'applicazione
    riparte solo dopo che le migrazioni sono state riapplicate.
    """
    trovato = re.search(r"alembic_version", indice)
    return "presente" if trovato else None


async def ripristina(percorso: Path, database: str | None = None) -> Esito:
    """Riporta il database al contenuto del file.

    `--clean --if-exists` toglie prima quello che c'è: senza, il ripristino si
    fermerebbe al primo oggetto già esistente e lascerebbe un database mezzo
    vecchio e mezzo nuovo. `--exit-on-error` perché un ripristino che prosegue
    dopo un errore è il modo peggiore di scoprirlo.
    """
    codice, _, errori = await _esegui(
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--exit-on-error",
        "--dbname",
        _ambiente_libpq(database)["PGDATABASE"],
        str(percorso),
        database=database,
    )
    if codice != 0:
        return _errore("Il ripristino non è riuscito.", errori, operazione="ripristino")
    return Esito(True, "Ripristino completato.")
