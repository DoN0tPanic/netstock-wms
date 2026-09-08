"""Gli elenchi che riempiono le tendine devono avere un ordine, e lo stesso.

Senza un ORDER BY completo PostgreSQL restituisce le righe nell'ordine fisico
della tabella: cambia a ogni modifica, perché la riga aggiornata viene riscritta
in fondo. Sulla tendina del modello si vedeva l'effetto — correggendo il nome di
un articolo un altro spariva dalle prime voci — e sfogliando due pagine la
stessa riga poteva comparire due volte e un'altra mai.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.api.v1.catalog_items import list_catalog_items
from app.api.v1.registries import locations_router
from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.enums import LocationType, UserRole


@dataclass
class _FakeUser:
    role: UserRole


_elenco_ubicazioni = next(
    rotta.endpoint for rotta in locations_router.routes if rotta.methods == {"GET"}  # type: ignore[attr-defined]
)


async def _semina_articoli(db, prefisso: str) -> list[str]:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    codici = [f"{prefisso}-{lettera}" for lettera in "EDCBA"]
    db.add_all(
        [
            CatalogItem(
                vendor_id=vendor.id,
                category_id=category.id,
                part_number=codice,
                name=f"Articolo {codice}",
                is_serialized=False,
            )
            for codice in codici
        ]
    )
    await db.flush()
    return sorted(codici)


async def _tutte_le_pagine(db, prefisso: str, misura: int) -> list[str]:
    visti: list[str] = []
    pagina = 1
    while True:
        risposta = await list_catalog_items(
            db=db,
            user=_FakeUser(role=UserRole.viewer),
            q=prefisso,
            page=pagina,
            page_size=misura,
        )
        visti.extend(articolo.part_number for articolo in risposta.items)
        if len(visti) >= risposta.total or not risposta.items:
            return visti
        pagina += 1


async def test_catalogo_in_ordine_alfabetico(app_db_session) -> None:
    prefisso = f"ORD{uuid.uuid4().hex[:6].upper()}"
    attesi = await _semina_articoli(app_db_session, prefisso)

    risposta = await list_catalog_items(
        db=app_db_session,
        user=_FakeUser(role=UserRole.viewer),
        q=prefisso,
        page=1,
        page_size=50,
    )
    assert [articolo.part_number for articolo in risposta.items] == attesi


async def test_le_pagine_non_ripetono_né_saltano_dopo_una_modifica(app_db_session) -> None:
    prefisso = f"ORD{uuid.uuid4().hex[:6].upper()}"
    attesi = await _semina_articoli(app_db_session, prefisso)

    # Due per pagina: con cinque articoli servono tre giri, che è dove
    # l'ordine instabile faceva danno.
    assert await _tutte_le_pagine(app_db_session, prefisso, 2) == attesi

    primo = (
        await app_db_session.execute(
            select(CatalogItem).where(CatalogItem.part_number == attesi[0])
        )
    ).scalar_one()
    primo.name = "Nome corretto dopo la creazione"
    await app_db_session.flush()

    # La riga modificata cambia posto nel file, non nell'elenco.
    assert await _tutte_le_pagine(app_db_session, prefisso, 2) == attesi


async def test_anagrafiche_in_ordine_di_codice(app_db_session) -> None:
    prefisso = f"ORD{uuid.uuid4().hex[:6].upper()}"
    codici = [f"{prefisso}-{lettera}" for lettera in "CAB"]
    app_db_session.add_all(
        [
            Location(code=codice, name=f"Ubicazione {codice}", type=LocationType.shelf)
            for codice in codici
        ]
    )
    await app_db_session.flush()

    risposta = await _elenco_ubicazioni(
        db=app_db_session,
        user=_FakeUser(role=UserRole.viewer),
        q=prefisso,
        page=1,
        page_size=50,
    )
    assert [ubicazione.code for ubicazione in risposta.items] == sorted(codici)
