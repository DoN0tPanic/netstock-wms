"""L'esito di una lettura: è servita, o è stata scartata?

Non è una statistica per curiosità. La lettura automatica dei documenti costa
un container, un modello da scaricare, un ADR di licenza e minuti di CPU per
documento: senza questo numero non c'è modo di decidere se tenerla. La colonna
`accepted` esisteva dal primo giorno e non l'ha mai scritta nessuna riga di
codice: letture registrate a decine, e zero informazioni su quante fossero
state usate.
"""
import uuid

import pytest
from sqlalchemy import select

from app.api.v1.extraction import registra_esito
from app.exceptions import NotFoundError
from app.models.enums import UserRole
from app.models.extraction import ExtractionRun
from app.models.users import User
from app.schemas.extraction import EsitoLetturaRequest


async def _utente(db, ruolo: UserRole = UserRole.admin) -> User:
    return (
        await db.execute(select(User).where(User.role == ruolo).limit(1))
    ).scalars().first()


async def _lettura(db, utente: User) -> ExtractionRun:
    run = ExtractionRun(
        user_id=utente.id,
        image_count=1,
        image_bytes=1024,
        engine="ocr+rules",
        fields_found={"serial_number": True},
        confidence={"serial_number": "high"},
        duration_ms=1200,
    )
    db.add(run)
    await db.flush()
    return run


async def test_una_lettura_usata_resta_segnata(app_db_session) -> None:
    utente = await _utente(app_db_session)
    run = await _lettura(app_db_session, utente)
    assert run.accepted is None  # nessuno ha ancora detto niente

    await registra_esito(run.id, EsitoLetturaRequest(accepted=True), app_db_session, utente)

    await app_db_session.refresh(run)
    assert run.accepted is True


async def test_una_lettura_scartata_si_distingue_da_una_senza_risposta(app_db_session) -> None:
    # Tre stati, non due: usata, scartata, e «non lo sappiamo». Confondere le
    # ultime due vorrebbe dire leggere come rifiuto ogni lettura interrotta.
    utente = await _utente(app_db_session)
    run = await _lettura(app_db_session, utente)

    await registra_esito(run.id, EsitoLetturaRequest(accepted=False), app_db_session, utente)

    await app_db_session.refresh(run)
    assert run.accepted is False


async def test_l_esito_lo_dichiara_solo_chi_ha_fatto_la_lettura(app_db_session) -> None:
    utente = await _utente(app_db_session)
    run = await _lettura(app_db_session, utente)
    altro = User(
        username=f"prova-esito-{uuid.uuid4().hex[:8]}",
        full_name="Un Altro",
        role=UserRole.operator,
    )
    app_db_session.add(altro)
    await app_db_session.flush()

    # Le letture di qualcun altro non si vedono e non si toccano: `fields_found`
    # dice quali campi ha trovato in un documento che non è tuo.
    with pytest.raises(NotFoundError):
        await registra_esito(run.id, EsitoLetturaRequest(accepted=True), app_db_session, altro)


async def test_una_lettura_inesistente_non_esplode(app_db_session) -> None:
    utente = await _utente(app_db_session)
    with pytest.raises(NotFoundError):
        await registra_esito(
            uuid.uuid4(), EsitoLetturaRequest(accepted=True), app_db_session, utente
        )
