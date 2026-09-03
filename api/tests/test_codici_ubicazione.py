"""Il codice di un'ubicazione ricavato dal nome.

Il codice serve — l'import ci riconosce l'ubicazione, e finisce sull'etichetta
dello scaffale — ma non c'è ragione di farlo inventare a chi crea
l'ubicazione. Quello che va garantito qui è che resti unico e che non cambi
sotto i piedi a chi l'etichetta l'ha già stampata.
"""
import uuid

import pytest
from sqlalchemy import select

from app.api.v1.registries import _location_code
from app.models.catalog import Location
from app.models.enums import LocationType
from app.services.codes import codice_da_nome, codice_libero


@pytest.mark.parametrize(
    ("nome", "atteso"),
    [
        ("Scaffale A01", "SCAFFALE-A01"),
        ("scaffale a01", "SCAFFALE-A01"),
        ("Área rientri", "AREA-RIENTRI"),  # gli accenti non entrano in un codice
        ("Sede  —  Nord Ovest", "SEDE-NORD-OVEST"),
        ("###", "UB"),  # un nome di soli simboli lascerebbe il codice vuoto
    ],
)
def test_dal_nome_al_codice(nome: str, atteso: str) -> None:
    assert codice_da_nome(nome) == atteso


def test_un_nome_lunghissimo_non_sfora() -> None:
    codice = codice_da_nome("Scaffale " * 20)
    assert len(codice) <= 32
    assert not codice.endswith("-")


async def test_due_ubicazioni_con_lo_stesso_nome_hanno_codici_diversi(app_db_session) -> None:
    # Succede davvero: «Scaffale A01» in due magazzini diversi. Il codice è
    # unico, quindi il secondo deve prendere una coda.
    nome = f"Scaffale {uuid.uuid4().hex[:6].upper()}"
    primo = await codice_libero(app_db_session, Location, nome)
    app_db_session.add(Location(code=primo, name=nome, type=LocationType.shelf))
    await app_db_session.flush()

    secondo = await codice_libero(app_db_session, Location, nome)

    assert secondo != primo
    assert secondo.startswith(primo)


async def test_chi_scrive_il_codice_se_lo_tiene(app_db_session) -> None:
    # Il valore generato è un'impostazione predefinita, non un'imposizione:
    # chi ha già una nomenclatura sua continua a usarla.
    valori = await _location_code(app_db_session, {"code": "  MIO-CODICE ", "name": "Scaffale A01"})
    assert valori["code"] == "MIO-CODICE"


async def test_senza_codice_lo_ricava_dal_nome(app_db_session) -> None:
    nome = f"Deposito {uuid.uuid4().hex[:6].upper()}"
    valori = await _location_code(app_db_session, {"code": None, "name": nome})
    assert valori["code"] == codice_da_nome(nome)


async def test_rinominare_non_cambia_il_codice(app_db_session) -> None:
    """Il codice si genera alla creazione e poi resta.

    È stampato su un'etichetta attaccata a uno scaffale e citato nei file di
    import di ieri: rigenerarlo a ogni rinomina vorrebbe dire che una
    correzione di battitura fa smettere di funzionare l'etichetta.
    """
    nome = f"Scaffale {uuid.uuid4().hex[:6].upper()}"
    valori = await _location_code(app_db_session, {"code": None, "name": nome})
    ubicazione = Location(code=valori["code"], name=nome, type=LocationType.shelf)
    app_db_session.add(ubicazione)
    await app_db_session.flush()

    ubicazione.name = "Un nome completamente diverso"
    await app_db_session.flush()

    riletta = (
        await app_db_session.execute(select(Location).where(Location.id == ubicazione.id))
    ).scalar_one()
    assert riletta.code == valori["code"]
