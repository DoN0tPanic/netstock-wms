"""Le correzioni del beta test di settembre, ognuna con la prova del difetto.

Ogni test qui sotto fallisce sul codice di prima: è scritto per il caso che
il beta test ha trovato, non per quello che sarebbe stato comodo provare.
"""

import uuid
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.deps import get_current_user
from app.errori_database import traduci
from app.exceptions import PasswordChangeRequiredError, ValidationAppError
from app.models.catalog import Category, Location, Vendor
from app.models.enums import LocationType, UserRole
from app.schemas.stock import IssueRequest, ReturnRequest, RmaOutRequest, TransferRequest
from app.services import maintenance
from app.services.extraction.rules import extract_field_from_text
from app.services.extraction.schemas import FieldSpec
from app.services.extraction.verifica_template import verifica_field_specs

# --- Errori del database: un rifiuto, non un guasto -------------------------


async def _errore_da(db, istruzione: str) -> IntegrityError:
    punto = await db.begin_nested()
    try:
        await db.execute(text(istruzione))
    except IntegrityError as errore:
        await punto.rollback()
        return errore
    await punto.rollback()
    raise AssertionError("l'istruzione doveva violare un vincolo")


async def test_un_codice_duplicato_e_un_409_con_un_messaggio_preciso(app_db_session) -> None:
    errore = await _errore_da(
        app_db_session, "INSERT INTO vendors (code, name) SELECT code, 'x' FROM vendors LIMIT 1"
    )
    stato, corpo = traduci(errore)
    assert stato == 409
    assert corpo["error"]["code"] == "DUPLICATE"
    assert corpo["error"]["message"] == "Esiste già un costruttore con questo codice."


async def test_una_quantita_a_zero_e_un_422(app_db_session) -> None:
    errore = await _errore_da(
        app_db_session,
        """
        WITH fornitore AS (
            INSERT INTO suppliers (name)
            VALUES ('Fornitore zero ' || gen_random_uuid())
            RETURNING id
        ), bolla AS (
            INSERT INTO delivery_notes (number, note_date, supplier_id, received_by)
            SELECT 'ZERO-' || gen_random_uuid(), current_date, fornitore.id,
                   (SELECT id FROM users LIMIT 1)
            FROM fornitore
            RETURNING id
        )
        INSERT INTO delivery_note_lines
            (delivery_note_id, line_number, catalog_item_id, qty_expected)
        SELECT bolla.id, 1, (SELECT id FROM catalog_items LIMIT 1), 0 FROM bolla""",
    )
    stato, corpo = traduci(errore)
    assert stato == 422
    assert corpo["error"]["message"] == "I pezzi attesi devono essere più di zero."


async def test_un_nome_utente_duplicato_e_detto_come_tale(app_db_session) -> None:
    errore = await _errore_da(
        app_db_session,
        """
        INSERT INTO users (username, full_name, role, auth_provider)
        SELECT username, 'x', 'viewer', 'local' FROM users LIMIT 1""",
    )
    stato, corpo = traduci(errore)
    assert (stato, corpo["error"]["message"]) == (409, "Questo nome utente è già in uso.")


# --- Ripristino: niente blocco su sé stesso, niente database a metà ---------


async def test_il_ripristino_gira_in_una_transazione_sola_e_con_un_tetto_ai_lucchetti(
    monkeypatch, tmp_path
) -> None:
    chiamate: list[tuple] = []

    async def finta(*comando, **opzioni):
        chiamate.append((comando, opzioni))
        return 0, b"", b""

    monkeypatch.setattr(maintenance, "_esegui", finta)
    esito = await maintenance.ripristina(tmp_path / "copia.dump")
    comando, opzioni = chiamate[0]
    assert esito.ok
    assert "--single-transaction" in comando
    assert opzioni.get("attesa_lucchetti") == maintenance.ATTESA_LUCCHETTI


async def test_un_lucchetto_conteso_diventa_un_messaggio_chiaro(monkeypatch, tmp_path) -> None:
    async def conteso(*comando, **opzioni):
        return (
            1,
            b"",
            b"pg_restore: error: could not execute query: "
            b"ERROR:  canceling statement due to lock timeout",
        )

    monkeypatch.setattr(maintenance, "_esegui", conteso)
    esito = await maintenance.ripristina(tmp_path / "copia.dump")
    assert not esito.ok
    assert "qualcuno sta usando" in esito.messaggio
    assert "Non è stato toccato niente" in esito.messaggio


async def test_l_attesa_dei_lucchetti_arriva_a_pg_restore(monkeypatch) -> None:
    # PGOPTIONS è il modo in cui il limite arriva davvero alla connessione di
    # pg_restore: controllarlo nell'ambiente del processo, non nel codice.
    catturato: dict = {}

    class Processo:
        returncode = 0

        async def communicate(self, _):
            return b"", b""

    async def crea(*comando, **opzioni):
        catturato.update(opzioni["env"])
        return Processo()

    monkeypatch.setattr(maintenance.asyncio, "create_subprocess_exec", crea)
    await maintenance._esegui("pg_restore", "--list", attesa_lucchetti="30s")
    assert catturato["PGOPTIONS"] == "-c lock_timeout=30s"


async def test_la_richiesta_chiude_la_propria_transazione_prima_di_ripristinare(
    monkeypatch, app_db_session
) -> None:
    # È la causa vera del blocco: leggere l'utente apriva una transazione che
    # restava aperta, con un lucchetto sulla tabella degli utenti, mentre
    # pg_restore aspettava proprio quel lucchetto per togliere i vincoli.
    import io

    from fastapi import UploadFile

    from app.api.v1.maintenance import ripristina_backup

    stato_al_ripristino: list[bool] = []

    async def indice_buono(percorso):
        return maintenance.Esito(True, "ok")

    async def ripristina_finto(percorso, database=None):
        stato_al_ripristino.append(app_db_session.in_transaction())
        return maintenance.Esito(True, "Ripristino completato.")

    monkeypatch.setattr(maintenance, "indice_dump", indice_buono)
    monkeypatch.setattr(maintenance, "ripristina", ripristina_finto)
    await app_db_session.execute(select(Vendor).limit(1))  # come la lettura dell'utente
    assert app_db_session.in_transaction()

    risposta = await ripristina_backup(
        db=app_db_session,
        conferma="RIPRISTINA",
        file=UploadFile(file=io.BytesIO(b"PGDMP"), filename="copia.dump"),
        user=SimpleNamespace(username="prova"),
    )
    assert risposta.ok
    assert stato_al_ripristino == [False], (
        "durante il ripristino la richiesta aveva ancora una transazione aperta"
    )


# --- Gerarchie: niente anelli -----------------------------------------------


def _aggiorna(router):
    return next(r.endpoint for r in router.routes if r.methods == {"PATCH"})


@dataclass
class _Utente:
    id: uuid.UUID
    username: str
    role: UserRole


async def _catena_di_ubicazioni(db):
    unico = uuid.uuid4().hex[:6].upper()
    radice = Location(code=f"ANR-{unico}", name="Radice", type=LocationType.warehouse)
    db.add(radice)
    await db.flush()
    figlio = Location(
        code=f"ANF-{unico}", name="Figlio", type=LocationType.shelf, parent_id=radice.id
    )
    db.add(figlio)
    await db.flush()
    nipote = Location(
        code=f"ANN-{unico}", name="Nipote", type=LocationType.box, parent_id=figlio.id
    )
    db.add(nipote)
    await db.flush()
    return radice, figlio, nipote


async def test_un_ubicazione_non_va_dentro_un_suo_discendente(app_db_session) -> None:
    from app.api.v1.registries import locations_router
    from app.schemas.catalog import LocationUpdate

    aggiorna = _aggiorna(locations_router)
    utente = _Utente(id=uuid.uuid4(), username="prova", role=UserRole.admin)
    radice, figlio, nipote = await _catena_di_ubicazioni(app_db_session)
    for nuovo_padre in (radice.id, figlio.id, nipote.id):
        with pytest.raises(ValidationAppError, match="anello"):
            await aggiorna(
                item_id=radice.id,
                payload=LocationUpdate(parent_id=nuovo_padre),
                db=app_db_session,
                user=utente,
            )


async def test_spostare_un_ramo_altrove_resta_possibile(app_db_session) -> None:
    from app.api.v1.registries import locations_router
    from app.models.users import User
    from app.schemas.catalog import LocationUpdate

    aggiorna = _aggiorna(locations_router)
    vero = (await app_db_session.execute(select(User).limit(1))).scalar_one()
    utente = _Utente(id=vero.id, username=vero.username, role=UserRole.admin)
    radice, figlio, nipote = await _catena_di_ubicazioni(app_db_session)
    altro, _, _ = await _catena_di_ubicazioni(app_db_session)
    spostato = await aggiorna(
        item_id=figlio.id,
        payload=LocationUpdate(parent_id=altro.id),
        db=app_db_session,
        user=utente,
    )
    assert spostato.parent_id == altro.id


async def test_una_categoria_non_va_dentro_la_propria_sottocategoria(app_db_session) -> None:
    from app.api.v1.registries import categories_router
    from app.schemas.catalog import CategoryUpdate

    aggiorna = _aggiorna(categories_router)
    utente = _Utente(id=uuid.uuid4(), username="prova", role=UserRole.admin)
    unico = uuid.uuid4().hex[:6].upper()
    madre = Category(code=f"CM-{unico}", name="Madre")
    app_db_session.add(madre)
    await app_db_session.flush()
    figlia = Category(code=f"CF-{unico}", name="Figlia", parent_id=madre.id)
    app_db_session.add(figlia)
    await app_db_session.flush()
    with pytest.raises(ValidationAppError, match="anello"):
        await aggiorna(
            item_id=madre.id,
            payload=CategoryUpdate(parent_id=figlia.id),
            db=app_db_session,
            user=utente,
        )


# --- Password provvisoria: l'obbligo vale anche per l'API --------------------


def _richiesta(percorso: str) -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": percorso, "headers": [], "query_string": b""}
    )


async def test_con_la_password_provvisoria_l_api_non_lascia_lavorare(
    monkeypatch, app_db_session
) -> None:
    utente = SimpleNamespace(must_change_password=True)

    async def trovato(db, token):
        return utente

    monkeypatch.setattr("app.deps.get_session_user", trovato)
    with pytest.raises(PasswordChangeRequiredError):
        await get_current_user(_richiesta("/api/v1/inventory"), app_db_session, "sessione")
    for libero in ("/api/v1/auth/me", "/api/v1/auth/change-password", "/api/v1/auth/logout"):
        assert await get_current_user(_richiesta(libero), app_db_session, "sessione") is utente


async def test_senza_obbligo_si_lavora_normalmente(monkeypatch, app_db_session) -> None:
    utente = SimpleNamespace(must_change_password=False)

    async def trovato(db, token):
        return utente

    monkeypatch.setattr("app.deps.get_session_user", trovato)
    assert (
        await get_current_user(_richiesta("/api/v1/inventory"), app_db_session, "sessione")
        is utente
    )


# --- Movimenti: un riferimento vero, un contenuto vero -----------------------

_LUOGO = str(uuid.uuid4())
_PEZZO = {"unit_id": str(uuid.uuid4())}


@pytest.mark.parametrize("riferimento", ["", "   ", "\t"])
def test_un_uscita_senza_riferimento_e_rifiutata(riferimento: str) -> None:
    with pytest.raises(ValidationError):
        IssueRequest(location_from_id=_LUOGO, reference=riferimento, items=[_PEZZO])


def test_un_uscita_vuota_e_rifiutata() -> None:
    with pytest.raises(ValidationError):
        IssueRequest(location_from_id=_LUOGO, reference="TICKET-1", items=[])


def test_il_riferimento_si_registra_ripulito() -> None:
    assert (
        IssueRequest(location_from_id=_LUOGO, reference="  TICKET-1 ", items=[_PEZZO]).reference
        == "TICKET-1"
    )


def test_uno_spostamento_o_un_reso_vuoto_sono_rifiutati() -> None:
    with pytest.raises(ValidationError):
        TransferRequest(location_to_id=_LUOGO)
    with pytest.raises(ValidationError):
        ReturnRequest(location_to_id=_LUOGO, reference="R-1")
    with pytest.raises(ValidationError):
        RmaOutRequest(
            location_from_id=_LUOGO, location_to_id=str(uuid.uuid4()), reference="R-1", unit_ids=[]
        )


# --- Template IA: controllati al salvataggio ---------------------------------


@pytest.mark.parametrize(
    "specifiche, motivo",
    [
        ({"serial_number": {"regex": "x"}}, "non riconosciute"),
        ({"fields": []}, "almeno un campo"),
        ({"fields": [{"name": "serial_number", "regex": "^[A-Z{3"}]}, "non è valida"),
        ({"fields": [{"name": "serial_number", "regx": "^A$"}]}, "regx"),
        ({"fields": [{"regex": "^A$"}]}, "manca il nome"),
        ({"fields": [{"name": "a"}, {"name": "a"}]}, "due volte"),
        ({"fields": [{"name": "a", "keyword_window": 0}]}, "positivo"),
        ({"fields": [{"name": "a", "keywords": "SN"}]}, "elenco"),
    ],
)
def test_un_template_sbagliato_e_rifiutato_con_il_motivo(specifiche, motivo: str) -> None:
    with pytest.raises(ValueError, match=motivo):
        verifica_field_specs(specifiche)


def test_un_template_giusto_passa() -> None:
    giusto = {
        "fields": [
            {
                "name": "serial_number",
                "regex": "^[A-Z]{3}[0-9]{4}[A-Z0-9]{4}$",
                "target": "unit.serial_number",
                "keywords": ["SN", "S/N"],
                "required": True,
                "keyword_window": 40,
                "ocr_fixes": True,
                "barcode_formats": ["Code128"],
                "match_against_catalog": False,
            }
        ],
        "llm_instructions": "Leggi il seriale.",
    }
    assert verifica_field_specs(giusto) is giusto


# --- Lettura della bolla: una data non è un numero ---------------------------

_NUMERO = FieldSpec(
    name="ddt_number",
    target="delivery_note.number",
    regex="[0-9]{1,10}(/[0-9]{2,4})?",
    keywords=["DDT", "N.", "NUMERO"],
    keyword_window=40,
)
_DATA = FieldSpec(
    name="ddt_date",
    target="delivery_note.note_date",
    regex=r"[0-3]?[0-9][/\-][0-1]?[0-9][/\-][0-9]{2,4}",
    keywords=["DATA", "DEL"],
    keyword_window=20,
)
_SERIALE = FieldSpec(
    name="serial_number",
    target="unit.serial_number",
    regex="^[A-Z]{3}[0-9]{4}[A-Z0-9]{4}$",
    keywords=["S/N", "SN"],
    keyword_window=40,
)


def _valore(testo: str, spec: FieldSpec) -> str | None:
    trovato = extract_field_from_text(testo, spec)
    return trovato.value if trovato else None


def test_un_pezzo_di_data_non_diventa_il_numero_della_bolla() -> None:
    # Il caso del beta test: il numero non è di sole cifre, e la lettura
    # ripiegava su «23/09», un pezzo della data. Meglio nessun numero che uno
    # sbagliato già compilato.
    assert _valore("DDT n. 777-G8BFX del 23/09/2026", _NUMERO) is None


@pytest.mark.parametrize(
    "testo, numero, data",
    [
        ("DDT n. 4521 del 23/09/2026", "4521", "23/09/2026"),
        ("DDT n. 4521/2026 del 23/09/2026", "4521/2026", "23/09/2026"),
        ("Documento di trasporto numero 88 data 01/10/26", "88", "01/10/26"),
    ],
)
def test_i_numeri_e_le_date_normali_si_leggono_come_prima(
    testo: str, numero: str, data: str
) -> None:
    assert _valore(testo, _NUMERO) == numero
    assert _valore(testo, _DATA) == data


@pytest.mark.parametrize("testo", ["S/N:ZZO0005TEST", "S/N ZZO0005TEST", "SN: ZZO0005TEST 1/2"])
def test_la_barra_fra_lettere_non_cambia_la_lettura_dei_seriali(testo: str) -> None:
    assert _valore(testo, _SERIALE) == "ZZO0005TEST"


# --- Errori di validazione: un rifiuto leggibile, mai un 500 ------------------


async def test_un_controllo_scritto_a_mano_diventa_un_422_leggibile() -> None:
    # Il rifacimento del beta test l'ha trovato nelle correzioni stesse: un
    # controllo che solleva ValueError metteva l'eccezione nel dettaglio
    # dell'errore, il JSON non si poteva scrivere e la risposta era un 500.
    import json

    from fastapi.exceptions import RequestValidationError

    from app.main import validation_error_handler

    try:
        TransferRequest(location_to_id=_LUOGO)
    except ValidationError as errore:
        risposta = await validation_error_handler(None, RequestValidationError(errore.errors()))
    corpo = json.loads(risposta.body)
    assert risposta.status_code == 422
    assert corpo["error"]["message"] == "Indica almeno un pezzo o una quantità."


@pytest.mark.parametrize("riuscito", [True, False])
async def test_dopo_un_ripristino_riuscito_le_connessioni_si_rinnovano(
    monkeypatch, app_db_session, riuscito: bool
) -> None:
    # Dopo il ripristino le tabelle sono nuove e le connessioni già aperte
    # ricordano i piani delle query su quelle vecchie: la prima richiesta su
    # ciascuna falliva con «cached statement plan is invalid». Se invece il
    # ripristino non è riuscito, il database è com'era e non c'è niente da
    # rinnovare.
    import io

    from fastapi import UploadFile

    from app.api.v1 import maintenance as endpoint

    rinnovate: list[bool] = []

    class Motore:
        async def dispose(self) -> None:
            rinnovate.append(True)

    async def indice_buono(percorso):
        return maintenance.Esito(True, "ok")

    async def ripristina_finto(percorso, database=None):
        return maintenance.Esito(riuscito, "fatto" if riuscito else "non riuscito")

    monkeypatch.setattr(maintenance, "indice_dump", indice_buono)
    monkeypatch.setattr(maintenance, "ripristina", ripristina_finto)
    monkeypatch.setattr(endpoint, "engine", Motore())
    await endpoint.ripristina_backup(
        db=app_db_session,
        conferma="RIPRISTINA",
        file=UploadFile(file=io.BytesIO(b"PGDMP"), filename="copia.dump"),
        user=SimpleNamespace(username="prova"),
    )
    assert rinnovate == ([True] if riuscito else [])
