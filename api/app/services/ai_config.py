"""Quale modello legge i documenti, deciso a caldo invece che al riavvio.

`EXTRACT_MODEL` nel file di configurazione si legge una volta sola all'avvio
del container: cambiarlo vuol dire entrare sulla macchina, modificare un file
e riavviare. Va bene per una scelta fatta una volta, non per una domanda che
torna — «adesso che c'è la scheda video, conviene il modello grande?».

Qui il valore vive in `app_settings`, come le altre impostazioni modificabili
(§6.2), con quello del file come punto di partenza. Chi cambia idea lo cambia
dalla pagina, e vale dalla lettura successiva.

Il valore si tiene in memoria per pochi secondi: leggerlo dal database a ogni
riga di un documento sarebbe una query per niente, e aspettare un minuto che
una scelta faccia effetto sarebbe una sorpresa.
"""

import time

from sqlalchemy import select

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.models.app_settings import AppSetting

CHIAVE_MODELLO = "extraction_model"
CHIAVE_MODALITA = "extraction_mode"
_VALIDITA_CACHE = 15.0

_cache: dict[str, tuple[float, str]] = {}


def invalida() -> None:
    """Da chiamare quando l'impostazione cambia: la scelta deve valere subito."""
    _cache.clear()


async def _valore(chiave: str, predefinito: str) -> str:
    scaduta = _cache.get(chiave)
    if scaduta is not None and time.monotonic() - scaduta[0] < _VALIDITA_CACHE:
        return scaduta[1]
    async with AsyncSessionLocal() as db:
        riga = (
            await db.execute(select(AppSetting).where(AppSetting.key == chiave))
        ).scalar_one_or_none()
    valore = predefinito
    if riga is not None and isinstance(riga.value, str) and riga.value.strip():
        valore = riga.value.strip()
    _cache[chiave] = (time.monotonic(), valore)
    return valore


async def modello() -> str:
    return await _valore(CHIAVE_MODELLO, get_settings().extract_model)


async def modalita() -> str:
    return await _valore(CHIAVE_MODALITA, get_settings().extract_mode)
