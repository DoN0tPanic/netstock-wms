"""Il modello che legge i documenti: quale è, quanto costa, e come cambiarlo.

Il problema che questa pagina risolve non è «impostare una stringa». Un nome
di modello vale solo se Ollama ce l'ha scaricato — sono gigabyte — e un campo
di testo libero permetterebbe di salvare `qwen3:32b`, vederlo accettato, e
scoprire che ogni lettura fallisce finché qualcuno non entra sulla macchina.
Qui si sceglie **fra quelli installati**, e se ne installa uno nuovo da qui.

L'altra metà è sapere se conviene cambiare, e a quella non risponde il nome
del modello: risponde quanto ci mette sul ferro che c'è. Per questo la pagina
mostra i tempi delle letture vere, presi da `extraction_runs`.
"""

from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select, text

from app.config import get_settings
from app.deps import DbSession, require_role
from app.exceptions import ValidationAppError
from app.models.app_settings import AppSetting
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.ai import ModelloRequest, StatoAiResponse
from app.services import ai_config
from app.services.audit import write_audit

router = APIRouter(prefix="/ai", tags=["ai"])
_log = structlog.get_logger("netstock.ai")

_TEMPI = """
    SELECT engine,
           count(*)                          AS letture,
           round(avg(duration_ms)/1000.0, 1) AS secondi_medi,
           round(max(duration_ms)/1000.0, 1) AS secondi_massimo,
           count(*) FILTER (WHERE accepted)  AS usate
    FROM extraction_runs
    WHERE ts > now() - interval '90 days'
    GROUP BY engine
    ORDER BY letture DESC
"""


async def _installati() -> tuple[list[dict[str, Any]], bool]:
    """I modelli che Ollama ha davvero, e se Ollama risponde."""
    impostazioni = get_settings()
    try:
        async with httpx.AsyncClient(base_url=impostazioni.ollama_base_url, timeout=10.0) as client:
            risposta = await client.get("/api/tags")
            risposta.raise_for_status()
            caricati = {
                m["name"]
                for m in (await client.get("/api/ps")).json().get("models", [])
            }
    except Exception as errore:
        _log.warning("ollama_irraggiungibile", errore=str(errore)[:200])
        return [], False

    modelli = []
    for voce in risposta.json().get("models", []):
        dettagli = voce.get("details", {})
        modelli.append(
            {
                "nome": voce["name"],
                "byte": voce.get("size", 0),
                "parametri": dettagli.get("parameter_size"),
                "quantizzazione": dettagli.get("quantization_level"),
                "in_memoria": voce["name"] in caricati,
            }
        )
    return sorted(modelli, key=lambda m: m["nome"]), True


@router.get("/stato", response_model=StatoAiResponse)
async def stato(
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    impostazioni = get_settings()
    modelli, raggiungibile = await _installati()
    tempi = [dict(riga._mapping) for riga in (await db.execute(text(_TEMPI)))]
    return StatoAiResponse(
        attiva=impostazioni.extract_enabled,
        modello_in_uso=await ai_config.modello(),
        modalita=await ai_config.modalita(),
        ollama_raggiungibile=raggiungibile,
        indirizzo_ollama=impostazioni.ollama_base_url,
        modelli=modelli,
        tempi=tempi,
    )


@router.put("/modello", response_model=StatoAiResponse)
async def scegli_modello(
    payload: ModelloRequest,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    """Cambia il modello in uso, fra quelli installati.

    La verifica che il modello esista **prima** di salvarlo è il punto di
    tutta la funzione: senza, si salva un nome plausibile e si scopre che non
    c'è alla prima bolla, quando serve.
    """
    modelli, raggiungibile = await _installati()
    if not raggiungibile:
        raise ValidationAppError(
            "Ollama non risponde: non posso verificare che il modello ci sia, e non lo salvo."
        )
    disponibili = {m["nome"] for m in modelli}
    if payload.modello not in disponibili:
        raise ValidationAppError(
            f"«{payload.modello}» non è installato. Scaricalo prima, oppure scegli fra: "
            + ", ".join(sorted(disponibili)),
            details={"installati": sorted(disponibili)},
        )

    for chiave, valore in ((ai_config.CHIAVE_MODELLO, payload.modello),
                           (ai_config.CHIAVE_MODALITA, payload.modalita)):
        if valore is None:
            continue
        riga = (
            await db.execute(select(AppSetting).where(AppSetting.key == chiave))
        ).scalar_one_or_none()
        if riga is None:
            db.add(AppSetting(key=chiave, value=valore, updated_by=user.id))
        else:
            riga.value = valore
            riga.updated_by = user.id
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="ai.model_change",
        details={"modello": payload.modello, "modalita": payload.modalita},
    )
    # Confermare **prima** di svuotare la cache, e non dopo. `ai_config` legge
    # con una sessione propria — deve poterlo fare anche da dentro una lettura
    # di documento, dove una sessione di richiesta non c'è — e una sessione
    # diversa non vede una scrittura solo `flush`ata. Invertendo i due passi,
    # la cache si riempiva daccapo con il valore vecchio e la risposta
    # mostrava il modello di prima: successo, e si vedeva.
    await db.commit()
    ai_config.invalida()
    return await stato(db, user)


# Qui c'era una rotta che chiedeva a Ollama di scaricare un modello, e non
# poteva funzionare: la rete `backend` è `internal: true` perché il container
# che vede il testo dei documenti non deve avere una via d'uscita verso
# internet (§7.5). La prova lo ha detto subito — «lookup registry.ollama.ai:
# server misbehaving» — ed è la risposta giusta, non un guasto.
#
# Farlo funzionare avrebbe voluto dire una delle due: dare l'uscita a quel
# container, o dare all'API il socket di Docker per avviarne un altro. La
# prima annulla una misura dichiarata e verificabile in audit; la seconda è
# peggio. Un modello si scarica una volta ogni tanto, e per quello c'è
# `scripts/ollama-pull.sh`, che usa un container usa e getta sulla rete
# normale e poi sparisce: il servizio resta isolato com'era.
#
# La pagina lo dice e mostra il comando, invece di offrire un pulsante che
# fallisce.
