"""Copia di sicurezza e ripristino.

Un backup si giudica su una cosa sola: che i dati tornino indietro. Qui il
giro si fa per davvero — si copia, si sporca il database, si ripristina, si
controlla che lo sporco sia sparito — perché la versione dove si verifica solo
che il file esista è precisamente quella che tradisce il giorno del disastro.

Gira sul database di prova: `conftest.py` si rifiuta di partire su un altro.
"""

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.services import maintenance

# Database usa e getta per la prova del giro completo: il ripristino ricrea
# ogni tabella, e farlo su quello degli altri test li fa cadere a seconda
# dell'ordine in cui girano. Successo davvero, la prima volta.
SCRATCH = "netstock_prova_ripristino"


def _url_diretto(database: str | None = None) -> str:
    impostazioni = get_settings()
    url = make_url(impostazioni.migrate_database_url or impostazioni.database_url)
    # `str(URL)` maschera la password con ***: serve chiederla esplicitamente,
    # o la connessione fallisce con un errore che parla di credenziali sbagliate.
    scelto = url.set(database=database) if database else url
    return scelto.render_as_string(hide_password=False)


async def _amministra(comando: str) -> None:
    """Crea o elimina un database: serve una connessione fuori transazione."""
    motore = create_async_engine(_url_diretto("postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with motore.connect() as connessione:
            await connessione.execute(text(comando))
    finally:
        await motore.dispose()


async def _conta_ubicazioni(database: str | None = None) -> int:
    """Connessione propria, aperta e chiusa: il ripristino deve poter togliere
    le tabelle, e una connessione lasciata aperta con una transazione dentro
    lo bloccherebbe."""
    motore = create_async_engine(_url_diretto(database))
    try:
        async with motore.connect() as connessione:
            return (await connessione.execute(text("SELECT count(*) FROM locations"))).scalar_one()
    finally:
        await motore.dispose()


async def _aggiungi_ubicazione(codice: str, database: str | None = None) -> None:
    motore = create_async_engine(_url_diretto(database))
    try:
        async with motore.begin() as connessione:
            await connessione.execute(
                text("INSERT INTO locations (code, name, type) VALUES (:c, :c, 'shelf')"),
                {"c": codice},
            )
    finally:
        await motore.dispose()


async def test_il_dump_si_crea_e_si_rilegge(tmp_path: Path) -> None:
    percorso = tmp_path / "copia.dump"

    creazione = await maintenance.crea_dump(percorso)
    assert creazione.ok, creazione.dettaglio
    assert percorso.stat().st_size > 0

    indice = await maintenance.indice_dump(percorso)
    assert indice.ok
    # L'indice deve contenere i dati, non solo lo scheletro: un dump senza
    # `TABLE DATA` si apre benissimo e non contiene niente.
    assert "TABLE DATA" in indice.dettaglio


async def test_un_file_qualsiasi_viene_rifiutato(tmp_path: Path) -> None:
    finto = tmp_path / "non-un-dump.dump"
    finto.write_bytes(b"questo non e' un archivio di postgres")

    esito = await maintenance.indice_dump(finto)

    # Il controllo sta prima di qualunque scrittura, apposta: un file sbagliato
    # va rifiutato mentre il database è ancora intatto.
    assert not esito.ok
    assert "non è una copia" in esito.messaggio


async def test_il_giro_completo_riporta_indietro_i_dati(tmp_path: Path) -> None:
    """Copia, sporca, ripristina: lo sporco deve essere sparito.

    Gira su un database usa e getta creato qui e buttato alla fine: il
    ripristino ricrea ogni tabella, e sul database condiviso dai test
    farebbe cadere quelli che girano dopo.
    """
    percorso = tmp_path / "prima.dump"
    assert (await maintenance.crea_dump(percorso)).ok

    await _amministra(f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)")
    await _amministra(f"CREATE DATABASE {SCRATCH}")
    try:
        # Primo ripristino: riempie il database vuoto.
        assert (await maintenance.ripristina(percorso, SCRATCH)).ok
        prima = await _conta_ubicazioni(SCRATCH)
        assert prima > 0

        await _aggiungi_ubicazione("RIPRISTINO-PROVA", SCRATCH)
        assert await _conta_ubicazioni(SCRATCH) == prima + 1

        # Secondo ripristino: qui `--clean` deve togliere quello che c'è.
        esito = await maintenance.ripristina(percorso, SCRATCH)

        assert esito.ok, esito.dettaglio
        assert await _conta_ubicazioni(SCRATCH) == prima, (
            "il ripristino non ha riportato indietro i dati"
        )
    finally:
        await _amministra(f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)")
