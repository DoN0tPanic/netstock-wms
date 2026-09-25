"""La giacenza per ubicazione si somma al magazzino che la contiene.

Le ubicazioni sono un albero — magazzino, scaffale, contenitore — e la merce
sta sugli scaffali. Raggruppando per ubicazione foglia, un deposito da mille
pezzi diventa venti barrette da cinquanta e non salta all'occhio niente, che è
esattamente la domanda a cui il grafico deve rispondere.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.api.v1.dashboard import get_dashboard
from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.enums import ItemCondition, LocationType, MovementType, UserRole
from app.models.movements import StockMovement
from app.models.users import User


@dataclass
class _FakeUser:
    role: UserRole


async def _carica(db, articolo: CatalogItem, ubicazione: Location, quanti: int) -> None:
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    db.add(
        StockMovement(
            occurred_at=datetime.now(UTC),
            type=MovementType.receipt,
            catalog_item_id=articolo.id,
            quantity=Decimal(quanti),
            condition=ItemCondition.new,
            location_to_id=ubicazione.id,
            performed_by=admin.id,
        )
    )
    await db.flush()


async def _articolo(db) -> CatalogItem:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    articolo = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"UBIC-{uuid.uuid4().hex[:8].upper()}",
        name="Articolo sfuso per la prova delle ubicazioni",
        is_serialized=False,
    )
    db.add(articolo)
    await db.flush()
    return articolo


def _riga(risultato, codice: str):
    return next((r for r in risultato.total_by_location if r.location_code == codice), None)


async def test_gli_scaffali_si_sommano_al_magazzino(app_db_session) -> None:
    unico = uuid.uuid4().hex[:6].upper()
    magazzino = Location(code=f"DEP-{unico}", name=f"Deposito {unico}", type=LocationType.warehouse)
    app_db_session.add(magazzino)
    await app_db_session.flush()
    scaffali = [
        Location(
            code=f"DEP-{unico}-S{n}",
            name=f"Scaffale {n}",
            type=LocationType.shelf,
            parent_id=magazzino.id,
        )
        for n in (1, 2, 3)
    ]
    app_db_session.add_all(scaffali)
    await app_db_session.flush()

    articolo = await _articolo(app_db_session)
    for scaffale, quanti in zip(scaffali, (5, 7, 9), strict=True):
        await _carica(app_db_session, articolo, scaffale, quanti)

    risultato = await get_dashboard(db=app_db_session, user=_FakeUser(role=UserRole.viewer))

    riga = _riga(risultato, magazzino.code)
    assert riga is not None, "il magazzino non compare: la merce sugli scaffali è sparita"
    assert riga.quantity == Decimal(21)
    assert riga.sublocations == 3
    # E gli scaffali non compaiono da soli: sarebbero la stessa merce due volte.
    for scaffale in scaffali:
        assert _riga(risultato, scaffale.code) is None


async def test_una_ubicazione_piatta_compare_come_se_stessa(app_db_session) -> None:
    # Dove non c'è gerarchia la radice di ognuna è sé stessa: il roll-up non
    # deve cambiare niente.
    unico = uuid.uuid4().hex[:6].upper()
    ubicazione = Location(
        code=f"PIATTA-{unico}", name="Deposito unico", type=LocationType.warehouse
    )
    app_db_session.add(ubicazione)
    await app_db_session.flush()
    articolo = await _articolo(app_db_session)
    await _carica(app_db_session, articolo, ubicazione, 4)

    risultato = await get_dashboard(db=app_db_session, user=_FakeUser(role=UserRole.viewer))

    riga = _riga(risultato, ubicazione.code)
    assert riga is not None
    assert riga.quantity == Decimal(4)
    assert riga.sublocations == 1


async def test_le_ubicazioni_arrivano_dalla_piu_carica_alla_meno(app_db_session) -> None:
    # È l'ordine che fa saltare all'occhio i magazzini più usati: il grafico
    # disegna le barre come arrivano.
    unico = uuid.uuid4().hex[:6].upper()
    ubicazioni = [
        Location(
            code=f"ORD-{unico}-{lettera}",
            name=f"Deposito {lettera}",
            type=LocationType.warehouse,
        )
        for lettera in "ABC"
    ]
    app_db_session.add_all(ubicazioni)
    await app_db_session.flush()
    articolo = await _articolo(app_db_session)
    for ubicazione, quanti in zip(ubicazioni, (3, 30, 12), strict=True):
        await _carica(app_db_session, articolo, ubicazione, quanti)

    risultato = await get_dashboard(db=app_db_session, user=_FakeUser(role=UserRole.viewer))

    nostre = [r for r in risultato.total_by_location if r.location_code.startswith(f"ORD-{unico}")]
    assert [r.quantity for r in nostre] == [Decimal(30), Decimal(12), Decimal(3)]
    quantita = [Decimal(r.quantity) for r in risultato.total_by_location]
    assert quantita == sorted(quantita, reverse=True), "l'elenco non è ordinato per quantità"


async def test_una_ubicazione_orfana_non_sparisce(app_db_session) -> None:
    # `parent_id` che punta a un'ubicazione dentro un ciclo non risale a
    # nessuna radice. Senza la rete del COALESCE quella merce sparirebbe dal
    # grafico in silenzio — il modo peggiore di sbagliare un totale.
    unico = uuid.uuid4().hex[:6].upper()
    primo = Location(code=f"CICLO-{unico}-A", name="Anello A", type=LocationType.shelf)
    secondo = Location(code=f"CICLO-{unico}-B", name="Anello B", type=LocationType.shelf)
    app_db_session.add_all([primo, secondo])
    await app_db_session.flush()
    primo.parent_id = secondo.id
    secondo.parent_id = primo.id
    await app_db_session.flush()

    articolo = await _articolo(app_db_session)
    await _carica(app_db_session, articolo, primo, 6)

    risultato = await get_dashboard(db=app_db_session, user=_FakeUser(role=UserRole.viewer))

    riga = _riga(risultato, primo.code)
    assert riga is not None, "la merce di un'ubicazione orfana è sparita dal grafico"
    assert riga.quantity == Decimal(6)
