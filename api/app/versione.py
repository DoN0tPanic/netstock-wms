"""Quale versione del codice sta girando, e da quando.

Il commit e la sua data li scrive la build dell'immagine in `versione.json`,
leggendoli dal `.git` del repository (vedi `api/Dockerfile`). Il codice non
può saperli da solo, e un numero di versione scritto a mano resterebbe fermo
per sempre. Fuori da un'immagine costruita così — i test, un avvio a mano —
il file non c'è, e la versione risulta sconosciuta invece che inventata.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

RADICE = Path(__file__).resolve().parent.parent
FILE_BUILD = RADICE / "versione.json"

# L'ora di avvio del processo: dopo un aggiornamento dice se il servizio è
# davvero ripartito, cosa che il commit da solo non basta a dire.
AVVIO = datetime.now(UTC)


def della_build(file: Path = FILE_BUILD) -> dict[str, str | None]:
    try:
        dati = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dati = {}
    if not isinstance(dati, dict):
        dati = {}
    return {chiave: (str(dati[chiave]) if dati.get(chiave) else None)
            for chiave in ("commit", "data_commit", "costruita")}


def revisione_prevista() -> str | None:
    """L'ultima migrazione che questo codice conosce: lo schema dovrebbe essere lì."""
    config = Config(str(RADICE / "alembic.ini"))
    config.set_main_option("script_location", str(RADICE / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()
