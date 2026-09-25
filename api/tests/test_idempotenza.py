"""La stessa operazione mandata due volte si registra una volta sola.

Il beta test l'ha misurato prima della correzione: la stessa ricezione di
merce sfusa, mandata due volte con la stessa chiave, aveva portato i cavi da
57 a 77 invece che a 67. Il browser mandava la chiave, il server la ignorava.
"""

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from starlette.requests import Request

from app.exceptions import ValidationAppError
from app.idempotenza import con_idempotenza
from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.enums import ItemCondition
from app.models.movements import StockMovement
from app.models.users import User
from app.schemas.stock import FreeReceiveResponse
from app.services.receiving import FreeReceiveLine, receive_free_stock


def _richiesta(
    corpo: dict, chiave: str | None, percorso: str = "/api/v1/movements/receive"
) -> Request:
    grezzo = json.dumps(corpo).encode()
    intestazioni = [(b"content-type", b"application/json")]
    if chiave is not None:
        intestazioni.append((b"idempotency-key", chiave.encode()))
    rotta = SimpleNamespace(response_model=FreeReceiveResponse, status_code=201)
    ambito = {
        "type": "http",
        "method": "POST",
        "path": percorso,
        "headers": intestazioni,
        "query_string": b"",
        "route": rotta,
    }

    async def ricevi() -> dict:
        return {"type": "http.request", "body": grezzo, "more_body": False}

    return Request(ambito, ricevi)


async def _prepara(db) -> tuple[User, CatalogItem, Location]:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    location = (await db.execute(select(Location).limit(1))).scalar_one()
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    articolo = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"IDEM-{uuid.uuid4().hex[:8]}",
        name="Cavo per l'idempotenza",
        is_serialized=False,
    )
    db.add(articolo)
    await db.flush()
    return admin, articolo, location


async def _carichi(db, articolo: CatalogItem) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.catalog_item_id == articolo.id)
        )
    ).scalar_one()


def _operazione(db, admin, articolo, location, quanti: int = 10):
    async def esegui():
        esito = await receive_free_stock(
            db,
            performer=admin,
            location_id=location.id,
            lines=[
                FreeReceiveLine(
                    catalog_item_id=articolo.id,
                    condition=ItemCondition.new,
                    serials=[],
                    quantity=Decimal(quanti),
                )
            ],
            confirm_warnings=set(),
            occurred_at=None,
        )
        return FreeReceiveResponse(
            created_unit_ids=esito.created_unit_ids, movement_ids=esito.movement_ids
        )

    return esegui


async def test_la_stessa_chiave_due_volte_registra_una_volta(app_db_session) -> None:
    admin, articolo, location = await _prepara(app_db_session)
    corpo = {"quanti": 10}
    chiave = f"k-{uuid.uuid4()}"

    prima = await con_idempotenza(
        _richiesta(corpo, chiave),
        app_db_session,
        admin,
        _operazione(app_db_session, admin, articolo, location),
    )
    ripetuta = await con_idempotenza(
        _richiesta(corpo, chiave),
        app_db_session,
        admin,
        _operazione(app_db_session, admin, articolo, location),
    )

    assert await _carichi(app_db_session, articolo) == 1
    assert isinstance(ripetuta, JSONResponse)
    assert ripetuta.status_code == 201
    assert ripetuta.headers["Idempotent-Replayed"] == "true"
    assert json.loads(ripetuta.body)["movement_ids"] == [str(m) for m in prima.movement_ids]


async def test_senza_chiave_ogni_invio_e_un_operazione(app_db_session) -> None:
    # La chiave protegge chi la manda, non obbliga chi non la manda: due
    # scatole uguali di cavi arrivate una dopo l'altra sono due carichi.
    admin, articolo, location = await _prepara(app_db_session)
    for _ in range(2):
        await con_idempotenza(
            _richiesta({"quanti": 10}, None),
            app_db_session,
            admin,
            _operazione(app_db_session, admin, articolo, location),
        )
    assert await _carichi(app_db_session, articolo) == 2


async def test_chiavi_diverse_sono_operazioni_diverse(app_db_session) -> None:
    admin, articolo, location = await _prepara(app_db_session)
    for chiave in (f"a-{uuid.uuid4()}", f"b-{uuid.uuid4()}"):
        await con_idempotenza(
            _richiesta({"quanti": 10}, chiave),
            app_db_session,
            admin,
            _operazione(app_db_session, admin, articolo, location),
        )
    assert await _carichi(app_db_session, articolo) == 2


async def test_stessa_chiave_con_dati_diversi_e_rifiutata(app_db_session) -> None:
    # È il caso della risposta persa e del modulo cambiato nel frattempo:
    # rifarlo alla cieca sarebbe il doppione che la chiave esiste a impedire.
    admin, articolo, location = await _prepara(app_db_session)
    chiave = f"k-{uuid.uuid4()}"
    await con_idempotenza(
        _richiesta({"quanti": 10}, chiave),
        app_db_session,
        admin,
        _operazione(app_db_session, admin, articolo, location),
    )
    with pytest.raises(ValidationAppError, match="già registrato"):
        await con_idempotenza(
            _richiesta({"quanti": 12}, chiave),
            app_db_session,
            admin,
            _operazione(app_db_session, admin, articolo, location, 12),
        )
    assert await _carichi(app_db_session, articolo) == 1


async def test_un_operazione_fallita_non_consuma_la_chiave(app_db_session) -> None:
    # Se l'operazione non va a buon fine la chiave sparisce con lei: il
    # nuovo tentativo, con la stessa chiave, deve poter registrare.
    admin, articolo, location = await _prepara(app_db_session)
    chiave = f"k-{uuid.uuid4()}"

    async def fallisce():
        raise ValidationAppError("qualcosa non va")

    punto = await app_db_session.begin_nested()
    with pytest.raises(ValidationAppError):
        await con_idempotenza(_richiesta({"quanti": 10}, chiave), app_db_session, admin, fallisce)
    await punto.rollback()

    await con_idempotenza(
        _richiesta({"quanti": 10}, chiave),
        app_db_session,
        admin,
        _operazione(app_db_session, admin, articolo, location),
    )
    assert await _carichi(app_db_session, articolo) == 1


async def test_una_chiave_troppo_lunga_e_rifiutata(app_db_session) -> None:
    admin, articolo, location = await _prepara(app_db_session)
    with pytest.raises(ValidationAppError, match="200"):
        await con_idempotenza(
            _richiesta({}, "x" * 201),
            app_db_session,
            admin,
            _operazione(app_db_session, admin, articolo, location),
        )
