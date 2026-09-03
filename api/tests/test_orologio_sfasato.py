"""Il movimento datato «adesso» da un orologio leggermente avanti.

Difetto vero, segnalato da chi lo ha subito: «Registra ricezione» su una
ricezione senza bolla falliva con «La data di ricezione non può essere nel
futuro». Il browser mandava la propria ora, quel PC era avanti di pochi
secondi rispetto al server, e tre secondi bastavano a bloccare l'intera
registrazione — con un messaggio che parla di date mentre il problema è un
orologio, e che a chi lo legge non lascia nessuna via d'uscita.

Il divieto (§6.6, punto 6) resta: serve a impedire di registrare merce
arrivata la settimana prossima. Quello che cambia è dove passa il confine.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.exceptions import ValidationAppError
from app.models.catalog import CatalogItem, Location
from app.models.enums import ItemCondition
from app.models.movements import StockMovement
from app.models.users import User
from app.services.movements import TOLLERANZA_OROLOGIO, validate_occurred_at
from app.services.receiving import FreeReceiveLine, SerialInput, receive_free_stock


def test_un_orologio_avanti_di_pochi_secondi_non_e_un_errore() -> None:
    fra_tre_secondi = datetime.now(UTC) + timedelta(seconds=3)
    assert validate_occurred_at(fra_tre_secondi) <= datetime.now(UTC)


def test_la_data_non_resta_nel_futuro_nel_registro() -> None:
    """Entro la tolleranza si riporta ad adesso, non si accetta com'è.

    Un movimento datato domani in un registro append-only è un dato che
    sembra corrotto a chi lo rilegge, e che una query «fino a oggi» non
    trova: la tolleranza serve a non rifiutare la richiesta, non a scrivere
    date che non esistono ancora.
    """
    prima = datetime.now(UTC)
    quando = validate_occurred_at(prima + timedelta(minutes=1))
    assert quando <= datetime.now(UTC)


def test_una_data_davvero_nel_futuro_resta_un_errore() -> None:
    domani = datetime.now(UTC) + TOLLERANZA_OROLOGIO + timedelta(minutes=1)
    with pytest.raises(ValidationAppError):
        validate_occurred_at(domani)


def test_il_passato_non_viene_toccato() -> None:
    # Registrare una bolla di ieri è previsto (§6.6, punto 6): la data
    # retrodatata deve arrivare al registro esattamente com'era.
    ieri = datetime.now(UTC) - timedelta(days=1)
    assert validate_occurred_at(ieri) == ieri


async def test_ricezione_senza_bolla_con_orologio_avanti(app_db_session) -> None:
    """Il caso segnalato, dall'inizio alla fine."""
    admin = (await app_db_session.execute(select(User).limit(1))).scalar_one()
    ubicazione = (await app_db_session.execute(select(Location).limit(1))).scalar_one()
    # Articolo senza `serial_pattern`: qui si misura l'orologio, e un avviso
    # sul formato del seriale porterebbe fuori strada il test.
    modello = (await app_db_session.execute(select(CatalogItem).limit(1))).scalar_one()
    articolo = CatalogItem(
        vendor_id=modello.vendor_id,
        category_id=modello.category_id,
        part_number=f"ORO-{uuid.uuid4().hex[:6].upper()}",
        name="Articolo per la prova dell'orologio",
        is_serialized=True,
    )
    app_db_session.add(articolo)
    await app_db_session.flush()
    seriale = f"ZZO{uuid.uuid4().hex[:4].upper()}TEST"

    esito = await receive_free_stock(
        app_db_session,
        performer=admin,
        location_id=ubicazione.id,
        lines=[
            FreeReceiveLine(
                catalog_item_id=articolo.id,
                condition=ItemCondition.new,
                serials=[SerialInput(serial_number=seriale)],
            )
        ],
        confirm_warnings=set(),
        occurred_at=datetime.now(UTC) + timedelta(seconds=3),
    )

    assert len(esito.movement_ids) == 1
    movimento = (
        await app_db_session.execute(
            select(StockMovement).where(StockMovement.id == esito.movement_ids[0])
        )
    ).scalar_one()
    assert movimento.occurred_at <= datetime.now(UTC)
