"""L'esportazione completa non deve rompersi quando il magazzino è grande.

PostgreSQL non accetta più di 32767 parametri in una sola istruzione. La
decorazione dei movimenti costruiva un `IN (…)` con un identificativo per ogni
pezzo citato: su una pagina sono al massimo duecento, ma l'archivio completo li
decora tutti insieme. Oltre i trentaduemila pezzi distinti nello storico
l'archivio completo rispondeva 500.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.api.v1 import movements as modulo_movimenti
from app.api.v1.movements import _decorate_movements
from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.enums import ItemCondition, MovementType, UnitStatus
from app.models.movements import StockMovement
from app.models.stock import StockUnit
from app.models.users import User


async def _semina_movimenti(db, quanti: int) -> list[StockMovement]:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    location = (await db.execute(select(Location).limit(1))).scalar_one()
    admin = (await db.execute(select(User).limit(1))).scalar_one()

    unico = uuid.uuid4().hex[:8].upper()
    articolo = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"SCAGL-{unico}",
        name="Articolo per la prova a scaglioni",
        is_serialized=True,
    )
    db.add(articolo)
    await db.flush()

    movimenti = []
    for indice in range(quanti):
        unita = StockUnit(
            catalog_item_id=articolo.id,
            serial_number=f"SCAGL{unico}{indice:03d}",
            status=UnitStatus.in_stock,
            condition=ItemCondition.new,
            location_id=location.id,
        )
        db.add(unita)
        await db.flush()
        movimento = StockMovement(
            occurred_at=datetime.now(UTC),
            type=MovementType.receipt,
            catalog_item_id=articolo.id,
            stock_unit_id=unita.id,
            quantity=Decimal("1"),
            condition=ItemCondition.new,
            location_to_id=location.id,
            performed_by=admin.id,
        )
        db.add(movimento)
        movimenti.append(movimento)
    await db.flush()
    return movimenti


async def test_decora_anche_oltre_il_limite_di_parametri(app_db_session, monkeypatch) -> None:
    # Due per scaglione su cinque movimenti: tre istruzioni invece di una.
    # Un'implementazione che sovrascrivesse invece di unire lascerebbe senza
    # seriale tutti i pezzi tranne quelli dell'ultimo scaglione.
    monkeypatch.setattr(modulo_movimenti, "_MASSIMO_PARAMETRI", 2)
    movimenti = await _semina_movimenti(app_db_session, 5)

    await _decorate_movements(app_db_session, movimenti)

    assert all(m.serial_number for m in movimenti), [m.serial_number for m in movimenti]
    assert all(m.part_number for m in movimenti)
    assert all(m.location_to_code for m in movimenti)
    assert all(m.performed_by_username for m in movimenti)
    assert len({m.serial_number for m in movimenti}) == 5


@pytest.mark.parametrize("scaglione", [1, 3, 100])
async def test_lo_scaglione_non_cambia_il_risultato(app_db_session, monkeypatch, scaglione) -> None:
    movimenti = await _semina_movimenti(app_db_session, 4)

    monkeypatch.setattr(modulo_movimenti, "_MASSIMO_PARAMETRI", scaglione)
    await _decorate_movements(app_db_session, movimenti)

    assert sorted(m.serial_number or "" for m in movimenti) == sorted(
        m.serial_number or "" for m in movimenti
    )
    assert all(m.serial_number for m in movimenti)
