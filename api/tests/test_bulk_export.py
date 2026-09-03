"""L'esportazione completa: un archivio, e dentro tutte le tabelle.

Il rischio di questa funzione non è che sbagli una query: è che un file
manchi, o che una colonna scivoli di uno rispetto alla sua intestazione. Sono
difetti che a schermo non si vedono — l'archivio si scarica lo stesso — e che
si scoprono quando qualcuno legge il foglio e trova le quantità sotto
«Condizione». Per questo qui si aprono i file e si contano le colonne.
"""
import csv
import io
import zipfile

from sqlalchemy import select, text

from app.api.v1.bulk_export import _FOGLI, export_everything
from app.models.audit import AuditLog
from app.models.users import User

ATTESI = {
    "LEGGIMI.txt",
    "giacenze.csv",
    "disponibilita.csv",
    "movimenti.csv",
    *(foglio.filename for foglio in _FOGLI),
}


async def _archivio(db) -> zipfile.ZipFile:
    user = (await db.execute(select(User).where(User.deleted_at.is_(None)).limit(1))).scalar_one()
    risposta = await export_everything(db, user)
    corpo = b"".join([pezzo async for pezzo in risposta.body_iterator])
    return zipfile.ZipFile(io.BytesIO(corpo))


def _righe(archivio: zipfile.ZipFile, nome: str) -> list[list[str]]:
    testo = archivio.read(nome).decode("utf-8-sig")
    return list(csv.reader(io.StringIO(testo), delimiter=";"))


async def test_l_archivio_contiene_tutti_i_fogli(app_db_session) -> None:
    archivio = await _archivio(app_db_session)
    assert set(archivio.namelist()) == ATTESI


async def test_ogni_riga_ha_le_colonne_della_sua_intestazione(app_db_session) -> None:
    archivio = await _archivio(app_db_session)
    for nome in archivio.namelist():
        if not nome.endswith(".csv"):
            continue
        righe = _righe(archivio, nome)
        assert righe, f"{nome} è vuoto: manca perfino l'intestazione"
        colonne = len(righe[0])
        for numero, riga in enumerate(righe[1:], start=2):
            assert len(riga) == colonne, f"{nome}, riga {numero}: {len(riga)} colonne su {colonne}"


async def test_le_giacenze_esportate_sono_tutte_quelle_che_ci_sono(app_db_session) -> None:
    # Il filtro vuoto deve voler dire «tutto»: se un giorno diventasse un
    # filtro qualsiasi, l'archivio sarebbe una copia parziale che non lo dice.
    unita = (await app_db_session.execute(text("SELECT count(*) FROM stock_units"))).scalar_one()
    archivio = await _archivio(app_db_session)
    righe = _righe(archivio, "giacenze.csv")
    unita_esportate = sum(1 for riga in righe[1:] if riga[0] == "Unità")
    assert unita_esportate == unita


async def test_i_valori_di_enum_arrivano_tradotti(app_db_session) -> None:
    archivio = await _archivio(app_db_session)
    righe = _righe(archivio, "ubicazioni.csv")
    tipi = {riga[2] for riga in righe[1:]}
    # `warehouse` in una colonna intitolata «Tipo» è il database che parla al
    # posto dell'applicazione.
    assert not tipi & {"warehouse", "shelf", "box", "remote_site", "transit"}


async def test_l_esportazione_integrale_lascia_una_riga_nel_registro(app_db_session) -> None:
    prima = (await app_db_session.execute(
        select(AuditLog).where(AuditLog.action == "export.all")
    )).scalars().all()
    await _archivio(app_db_session)
    dopo = (await app_db_session.execute(
        select(AuditLog).where(AuditLog.action == "export.all")
    )).scalars().all()
    # Portare fuori l'intero magazzino è raro e vale una riga: è il genere di
    # cosa per cui il registro esiste. Gli accessi, che sono migliaia, no.
    assert len(dopo) == len(prima) + 1
