"""Import del catalogo e della giacenza di partenza.

Quello che va garantito qui non è che il file si legga: è che un file
sbagliato non entri a metà. Un import che crea duecento articoli e poi si
ferma sull'errore della riga 201 lascia un magazzino che non è né quello di
prima né quello nuovo, e capire dove si è fermato costa più che rifare tutto.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.exceptions import ValidationAppError
from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.movements import StockMovement
from app.models.stock import StockUnit
from app.models.users import User
from app.services.imports import (
    RIFERIMENTO_INIZIALE,
    importa_catalogo,
    importa_giacenza,
    leggi_csv,
)


async def _admin(db) -> User:
    return (
        await db.execute(select(User).where(User.role == "admin").limit(1))
    ).scalars().first()


async def _codici(db) -> tuple[str, str, str]:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    categoria = (await db.execute(select(Category).limit(1))).scalar_one()
    ubicazione = (await db.execute(select(Location).limit(1))).scalar_one()
    return vendor.code, categoria.code, ubicazione.code


def test_legge_le_intestazioni_dell_esportazione() -> None:
    # Il giro che questo import esiste per rendere possibile: si esporta, si
    # corregge in Excel, si reimporta. Se le intestazioni non combaciassero,
    # il file prodotto dal sistema non sarebbe leggibile dal sistema.
    testo = (
        "﻿Codice articolo;Nome;Fornitore;Categoria;Serializzato;Quantità\n"
        "SW-1;Switch;CSC;SWITCH;Sì;3\n"
    )
    righe = leggi_csv(testo)
    assert righe == [
        {
            "part_number": "SW-1",
            "nome": "Switch",
            "vendor": "CSC",
            "categoria": "SWITCH",
            "serializzato": "Sì",
            "quantita": "3",
        }
    ]


def test_accetta_anche_la_virgola_e_i_nomi_semplici() -> None:
    # Un file salvato fuori dall'Italia arriva con la virgola, e chi scrive a
    # mano l'intestazione scrive `part_number`. Nessuno dei due è un motivo
    # per rifiutare il file.
    righe = leggi_csv("part_number,seriale,ubicazione\nSW-1,ABC,MAG\n")
    assert righe[0]["part_number"] == "SW-1"
    assert righe[0]["ubicazione"] == "MAG"


async def test_catalogo_rifiuta_tutto_se_un_fornitore_non_esiste(app_db_session) -> None:
    vendor, categoria, _ = await _codici(app_db_session)
    prima = (
        await app_db_session.execute(select(func.count()).select_from(CatalogItem))
    ).scalar_one()

    rapporto = await importa_catalogo(
        app_db_session,
        [
            {"part_number": "IMP-1", "nome": "Buono", "vendor": vendor, "categoria": categoria},
            {"part_number": "IMP-2", "nome": "Cattivo", "vendor": "NONESISTE",
             "categoria": categoria},
        ],
    )

    # La riga buona è contata come creabile, ma il rapporto non è valido: sta
    # al chiamante non applicare niente. Crearne una e scartare l'altra
    # lascerebbe un catalogo a metà, che è il caso peggiore.
    assert not rapporto.valido
    assert "NONESISTE" in rapporto.errori[0]
    await app_db_session.rollback()
    dopo = (
        await app_db_session.execute(select(func.count()).select_from(CatalogItem))
    ).scalar_one()
    assert dopo == prima


async def test_catalogo_non_ricrea_quello_che_c_e_gia(app_db_session) -> None:
    vendor, categoria, _ = await _codici(app_db_session)
    esistente = (await app_db_session.execute(select(CatalogItem).limit(1))).scalar_one()
    vendor_esistente = (
        await app_db_session.execute(
            select(Vendor).where(Vendor.id == esistente.vendor_id)
        )
    ).scalar_one()

    rapporto = await importa_catalogo(
        app_db_session,
        [{"part_number": esistente.part_number, "nome": "Doppione",
          "vendor": vendor_esistente.code, "categoria": categoria}],
    )

    assert rapporto.creati == 0
    assert "già in catalogo" in rapporto.saltati[0]


async def test_giacenza_diventa_movimenti_non_righe_inserite(app_db_session) -> None:
    """Il punto di tutto l'import: la giacenza qui è la somma dei movimenti.

    Scrivere le unità dritte nella tabella sarebbe stato più corto e avrebbe
    scavalcato il ledger append-only al primo uso vero del sistema.
    """
    admin = await _admin(app_db_session)
    vendor, categoria, ubicazione = await _codici(app_db_session)
    codice = f"IMP-SER-{uuid.uuid4().hex[:6].upper()}"
    await importa_catalogo(
        app_db_session,
        [{"part_number": codice, "nome": "Serializzato", "vendor": vendor,
          "categoria": categoria, "serializzato": "Sì"}],
    )
    seriale = f"ZZO{uuid.uuid4().hex[:4].upper()}TEST"

    rapporto = await importa_giacenza(
        app_db_session,
        [{"part_number": codice, "seriale": seriale, "ubicazione": ubicazione,
          "condizione": "Nuovo"}],
        performer=admin,
    )

    assert rapporto.valido and rapporto.creati == 1
    unita = (
        await app_db_session.execute(
            select(StockUnit).where(StockUnit.serial_number == seriale)
        )
    ).scalar_one()
    movimento = (
        await app_db_session.execute(
            select(StockMovement).where(StockMovement.stock_unit_id == unita.id)
        )
    ).scalar_one()
    assert movimento.performed_by == admin.id
    # Senza riferimento, fra due anni questo carico sarebbe indistinguibile da
    # merce trovata in magazzino e registrata a mano.
    assert movimento.reference == RIFERIMENTO_INIZIALE


async def test_lo_sfuso_si_somma_per_ubicazione(app_db_session) -> None:
    admin = await _admin(app_db_session)
    vendor, categoria, ubicazione = await _codici(app_db_session)
    codice = f"IMP-BULK-{uuid.uuid4().hex[:6].upper()}"
    await importa_catalogo(
        app_db_session,
        [{"part_number": codice, "nome": "Sfuso", "vendor": vendor,
          "categoria": categoria, "serializzato": "No"}],
    )

    rapporto = await importa_giacenza(
        app_db_session,
        [
            {"part_number": codice, "ubicazione": ubicazione, "quantita": "120"},
            {"part_number": codice, "ubicazione": ubicazione, "quantita": "30,5"},
        ],
        performer=admin,
    )

    # Due righe, un movimento solo: sono lo stesso articolo nella stessa
    # ubicazione e nella stessa condizione. La virgola decimale è quella che
    # esce da Excel in italiano.
    assert rapporto.creati == 1
    totale = (
        await app_db_session.execute(
            text(
                "SELECT sum(quantity) FROM stock_movements m "
                "JOIN catalog_items ci ON ci.id = m.catalog_item_id "
                "WHERE ci.part_number = :codice"
            ),
            {"codice": codice},
        )
    ).scalar_one()
    assert totale == Decimal("150.5")


async def test_un_serializzato_senza_seriale_e_un_errore(app_db_session) -> None:
    admin = await _admin(app_db_session)
    vendor, categoria, ubicazione = await _codici(app_db_session)
    codice = f"IMP-NOSER-{uuid.uuid4().hex[:6].upper()}"
    await importa_catalogo(
        app_db_session,
        [{"part_number": codice, "nome": "Serializzato", "vendor": vendor,
          "categoria": categoria, "serializzato": "Sì"}],
    )

    rapporto = await importa_giacenza(
        app_db_session,
        [{"part_number": codice, "ubicazione": ubicazione, "quantita": "5"}],
        performer=admin,
    )

    # Cinque switch senza seriale non sono cinque switch: sono cinque righe
    # che nessuno potrà più ricondurre a un apparato.
    assert not rapporto.valido
    assert "non ha seriale" in rapporto.errori[0]


async def test_un_seriale_gia_a_magazzino_non_entra_due_volte(app_db_session) -> None:
    admin = await _admin(app_db_session)
    vendor, categoria, ubicazione = await _codici(app_db_session)
    codice = f"IMP-DUP-{uuid.uuid4().hex[:6].upper()}"
    await importa_catalogo(
        app_db_session,
        [{"part_number": codice, "nome": "Serializzato", "vendor": vendor,
          "categoria": categoria, "serializzato": "Sì"}],
    )
    seriale = f"ZZO{uuid.uuid4().hex[:4].upper()}TEST"
    riga = {"part_number": codice, "seriale": seriale, "ubicazione": ubicazione}
    await importa_giacenza(app_db_session, [riga], performer=admin)

    # Rilanciare l'import dello stesso file è la cosa più naturale del mondo
    # quando la prima volta si è interrotta a metà. Il rifiuto arriva dalla
    # stessa validazione che protegge la ricezione a mano: l'import non ha una
    # sua idea di cosa sia un doppione.
    with pytest.raises(ValidationAppError):
        await importa_giacenza(app_db_session, [dict(riga)], performer=admin)


async def test_ubicazione_inesistente_non_scrive_niente(app_db_session) -> None:
    admin = await _admin(app_db_session)
    prima = (
        await app_db_session.execute(select(func.count()).select_from(StockMovement))
    ).scalar_one()

    rapporto = await importa_giacenza(
        app_db_session,
        [{"part_number": "QUALSIASI", "ubicazione": "SCAFFALE-CHE-NON-C-E", "quantita": "1"}],
        performer=admin,
    )

    assert not rapporto.valido
    dopo = (
        await app_db_session.execute(select(func.count()).select_from(StockMovement))
    ).scalar_one()
    assert dopo == prima
