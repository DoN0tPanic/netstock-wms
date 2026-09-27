"""La pagina Impostazioni dice quale versione gira.

Questi test tengono fermo cosa risponde l'endpoint, anche quando il file che
la build scrive manca o è rovinato: la pagina deve dire «sconosciuta», non
cadere. I permessi li prova `docs/10-verifica/endpoint.sh`, dal vivo.
"""

import json
from types import SimpleNamespace

from app.api.v1.versione import versione
from app.models.enums import UserRole
from app.versione import RADICE, della_build, revisione_prevista

VUOTA = {"commit": None, "data_commit": None, "costruita": None}


async def test_schema_attuale_e_previsto_coincidono_dopo_le_migrazioni(app_db_session) -> None:
    risposta = await versione(db=app_db_session, user=SimpleNamespace(role=UserRole.admin))
    assert risposta.schema_attuale == risposta.schema_previsto == revisione_prevista()
    assert risposta.python.startswith("3.")
    assert risposta.postgresql.split(".")[0].isdigit()


def test_la_revisione_prevista_e_l_ultima_migrazione() -> None:
    migrazioni = sorted(p.name.split("_")[0] for p in (RADICE / "alembic/versions").glob("0*.py"))
    assert revisione_prevista() == migrazioni[-1]


def test_senza_file_di_build_la_versione_e_sconosciuta(tmp_path) -> None:
    assert della_build(tmp_path / "non-esiste.json") == VUOTA


def test_un_file_rovinato_non_rompe_la_pagina(tmp_path) -> None:
    file = tmp_path / "versione.json"
    for contenuto in ("{non è json", '["un elenco"]', '{"commit": ""}'):
        file.write_text(contenuto)
        assert della_build(file) == VUOTA


def test_legge_commit_e_date(tmp_path) -> None:
    dati = {
        "commit": "7faa702",
        "data_commit": "2026-09-27T11:55:00+02:00",
        "costruita": "2026-09-28T07:00:00Z",
    }
    file = tmp_path / "versione.json"
    file.write_text(json.dumps(dati))
    assert della_build(file) == dati
