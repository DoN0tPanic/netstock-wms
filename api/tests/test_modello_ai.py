"""Il modello in uso: si cambia a caldo, e solo fra quelli installati.

Le due cose che questa funzione deve garantire, e che si rompono in silenzio
se nessuno le prova: che un nome non installato venga rifiutato **prima** di
essere salvato, e che una scelta salvata valga dalla lettura successiva invece
che dopo un riavvio.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.api.v1.ai import scegli_modello, stato
from app.exceptions import ValidationAppError
from app.models.app_settings import AppSetting
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.ai import ModelloRequest
from app.services import ai_config

INSTALLATI = [
    {"nome": "qwen3:4b", "byte": 2_500_000_000, "parametri": "4.0B",
     "quantizzazione": "Q4_K_M", "in_memoria": True},
    {"nome": "phi4-mini:latest", "byte": 2_500_000_000, "parametri": "3.8B",
     "quantizzazione": "Q4_K_M", "in_memoria": False},
]


async def _admin(db) -> User:
    return (
        await db.execute(select(User).where(User.role == UserRole.admin).limit(1))
    ).scalars().first()


async def test_un_modello_non_installato_viene_rifiutato(app_db_session) -> None:
    """Il controllo sta prima del salvataggio, ed è tutto il punto.

    Senza, si salva un nome plausibile, la pagina dice di sì, e si scopre che
    non c'è alla prima bolla — cioè quando serve.
    """
    utente = await _admin(app_db_session)
    with (
        patch("app.api.v1.ai._installati", return_value=(INSTALLATI, True)),
        pytest.raises(ValidationAppError) as rifiuto,
    ):
        await scegli_modello(ModelloRequest(modello="qwen3:32b"), app_db_session, utente)
    assert "non è installato" in rifiuto.value.message
    # E il messaggio dice quali ci sono, invece di lasciare a indovinare.
    assert "qwen3:4b" in rifiuto.value.message


async def test_se_ollama_non_risponde_non_si_salva_niente(app_db_session) -> None:
    # Non potendo verificare, si rifiuta: salvare alla cieca vorrebbe dire
    # scoprire l'errore quando Ollama torna, e non ora.
    utente = await _admin(app_db_session)
    with (
        patch("app.api.v1.ai._installati", return_value=([], False)),
        pytest.raises(ValidationAppError) as rifiuto,
    ):
        await scegli_modello(ModelloRequest(modello="qwen3:4b"), app_db_session, utente)
    assert "non risponde" in rifiuto.value.message


async def test_la_scelta_vale_dalla_lettura_successiva(app_db_session) -> None:
    """Non dopo un riavvio: è la ragione per cui il valore sta nel database."""
    utente = await _admin(app_db_session)
    ai_config.invalida()
    try:
        with patch("app.api.v1.ai._installati", return_value=(INSTALLATI, True)):
            await scegli_modello(
                ModelloRequest(modello="phi4-mini:latest"), app_db_session, utente
            )
        # `ai_config.modello()` legge con una sessione propria — deve poterlo
        # fare anche da dentro la lettura di un documento, dove una sessione
        # di richiesta non c'è: se il salvataggio non fosse confermato, qui si
        # rileggerebbe il valore vecchio. È successo davvero.
        assert await ai_config.modello() == "phi4-mini:latest"

        salvata = (
            await app_db_session.execute(
                select(AppSetting).where(AppSetting.key == ai_config.CHIAVE_MODELLO)
            )
        ).scalar_one()
        assert salvata.value == "phi4-mini:latest"
    finally:
        # La prova scrive per davvero (deve: il difetto stava nel commit):
        # si rimette com'era.
        with patch("app.api.v1.ai._installati", return_value=(INSTALLATI, True)):
            await scegli_modello(
                ModelloRequest(modello="qwen3:4b"), app_db_session, utente
            )
        ai_config.invalida()


async def test_lo_stato_dice_cosa_c_e_e_quanto_costa(app_db_session) -> None:
    utente = await _admin(app_db_session)
    with patch("app.api.v1.ai._installati", return_value=(INSTALLATI, True)):
        risposta = await stato(app_db_session, utente)

    assert risposta.ollama_raggiungibile is True
    assert [m["nome"] for m in risposta.modelli] == ["qwen3:4b", "phi4-mini:latest"]
    # I tempi vengono da `extraction_runs`: possono essere vuoti su
    # un'installazione nuova, ma la chiave c'è sempre.
    assert isinstance(risposta.tempi, list)
