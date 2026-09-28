"""Gli avvisi che proteggono la produzione, uno per guaio già successo.

Ogni caso si costruisce in una cartella temporanea che imita quella dei
backup: le date dei file si spostano con os.utime, lo spazio su disco si
finge sostituendo shutil.disk_usage.
"""

import json
import os
from collections import namedtuple
from types import SimpleNamespace

from app.api.v1.avvisi import avvisi as endpoint_avvisi
from app.models.enums import UserRole
from app.services import avvisi

ORA = 1_800_000_000.0  # un istante fisso: i test non dipendono da quando girano


def _copia(cartella, nome, byte=1024, ore_fa=1.0, sotto="daily"):
    (cartella / sotto).mkdir(parents=True, exist_ok=True)
    file = cartella / sotto / nome
    file.write_bytes(b"x" * byte)
    os.utime(file, (ORA - ore_fa * 3600, ORA - ore_fa * 3600))
    return file


def _stato(cartella, **campi):
    dati = {"quando": "2027-01-15T02:30:00Z", "esito": "riuscito", "remoto": "riuscito",
            "prova_ripristino": "attiva", "ultima_prova_ripristino": "2027-01-14T02:31:00Z"}
    dati.update(campi)
    (cartella / avvisi.FILE_STATO).write_text(json.dumps(dati))


def _codici(elenco):
    return sorted(a.codice for a in elenco)


def test_tutto_a_posto_nessun_avviso(tmp_path):
    _copia(tmp_path, "netstock-20270115-023000.dump")
    _stato(tmp_path, ultima_prova_ripristino="2027-01-14T00:00:00Z")
    assert avvisi.controlla_backup(tmp_path, adesso=ORA) == []


def test_cartella_non_montata(tmp_path):
    elenco = avvisi.controlla_backup(tmp_path / "manca", adesso=ORA)
    assert _codici(elenco) == ["backup_cartella_assente"]


def test_nessuna_copia(tmp_path):
    (tmp_path / "daily").mkdir()
    assert _codici(avvisi.controlla_backup(tmp_path, adesso=ORA)) == ["backup_assente"]


def test_ultima_copia_buona_troppo_vecchia(tmp_path):
    _copia(tmp_path, "vecchia.dump", ore_fa=avvisi.ORE_MASSIME_SENZA_BACKUP + 1)
    elenco = avvisi.controlla_backup(tmp_path, adesso=ORA)
    assert _codici(elenco) == ["backup_vecchio"]
    assert elenco[0].gravita == "critico"


def test_una_notte_saltata_non_e_ancora_un_allarme(tmp_path):
    _copia(tmp_path, "ieri.dump", ore_fa=30)
    assert avvisi.controlla_backup(tmp_path, adesso=ORA) == []


def test_ultima_copia_vuota_come_il_20_settembre(tmp_path):
    # Il caso vero: un dump da 0 byte dopo copie buone. L'ultima buona è
    # recente, ma quella di stanotte è vuota.
    _copia(tmp_path, "buona.dump", ore_fa=20)
    _copia(tmp_path, "vuota.dump", byte=0, ore_fa=1)
    elenco = avvisi.controlla_backup(tmp_path, adesso=ORA)
    assert _codici(elenco) == ["backup_vuoto"]
    assert "vuota.dump" in elenco[0].dettaglio


def test_esiti_scritti_da_backup_sh(tmp_path):
    _copia(tmp_path, "oggi.dump")
    _stato(tmp_path, esito="fallito", remoto="fallito")
    elenco = avvisi.controlla_backup(tmp_path, adesso=ORA)
    assert _codici(elenco) == ["backup_fallito", "backup_remoto_fallito"]
    _stato(tmp_path, remoto="non configurato")
    elenco = avvisi.controlla_backup(tmp_path, adesso=ORA)
    assert _codici(elenco) == ["backup_solo_locale"]
    assert elenco[0].gravita == "attenzione"


def test_prova_di_ripristino_ferma_o_disattivata(tmp_path):
    _copia(tmp_path, "oggi.dump")
    _stato(tmp_path, ultima_prova_ripristino="2026-12-01T00:00:00Z")
    assert _codici(avvisi.controlla_backup(tmp_path, adesso=ORA)) == ["prova_ripristino_ferma"]
    _stato(tmp_path, ultima_prova_ripristino=None)
    assert "mai riuscita" in avvisi.controlla_backup(tmp_path, adesso=ORA)[0].titolo
    # Spenta per scelta (BACKUP_RESTORE_TEST=0): è una decisione, non un guasto.
    _stato(tmp_path, prova_ripristino="disattivata", ultima_prova_ripristino=None)
    assert avvisi.controlla_backup(tmp_path, adesso=ORA) == []


def test_stato_illeggibile_non_rompe_niente(tmp_path):
    _copia(tmp_path, "oggi.dump")
    (tmp_path / avvisi.FILE_STATO).write_text("{non è json")
    assert avvisi.controlla_backup(tmp_path, adesso=ORA) == []


Uso = namedtuple("Uso", "total used free")


def test_disco_sotto_sopra_e_oltre_la_soglia(tmp_path, monkeypatch):
    for usato, atteso in ((80, []), (87, ["attenzione"]), (96, ["critico"])):
        uso = Uso(100 * 1024**3, usato * 1024**3, (100 - usato) * 1024**3)
        monkeypatch.setattr(avvisi.shutil, "disk_usage", lambda _percorso, uso=uso: uso)
        elenco = avvisi.controlla_disco((tmp_path,))
        assert [a.gravita for a in elenco] == atteso
    assert elenco[0].titolo == "Disco quasi pieno: 96% occupato"


def test_l_endpoint_porta_l_ora_del_server(monkeypatch):
    monkeypatch.setattr(avvisi, "CARTELLA_BACKUP", avvisi.CARTELLA_BACKUP)
    risposta = endpoint_avvisi(user=SimpleNamespace(role=UserRole.admin))
    assert risposta.ora_server.tzinfo is not None
    assert all(a.gravita in ("critico", "attenzione") for a in risposta.avvisi)
