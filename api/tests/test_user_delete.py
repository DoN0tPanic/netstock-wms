"""Eliminazione di un utente, nei due passi che il registro impone.

Eliminare chiude l'account: vale sempre, e si disfa. Toglierlo dal database è
un secondo gesto, possibile solo per chi non ha firmato nulla — chi ha firmato
non si rimuove senza riscrivere un registro append-only, e non si rimuoverà
mai. I due passi erano una chiamata sola che sceglieva da sé, e l'account
senza storia spariva senza comparire fra gli eliminati: dall'esterno era
indistinguibile da un'eliminazione fallita.
"""
import uuid

import pytest
from sqlalchemy import select, text

from app.api.v1.users import (
    USER_REFERENCES,
    create_user,
    delete_user,
    list_users,
    purge_user,
    restore_user,
    update_user,
)
from app.exceptions import NotFoundError, ValidationAppError
from app.models.enums import UserRole
from app.models.users import Session, User
from app.schemas.users import UserCreate, UserUpdate
from app.services.audit import write_audit


async def _admin(db) -> User:
    stmt = select(User).where(User.role == UserRole.admin, User.is_active.is_(True))
    return (await db.execute(stmt)).scalars().first()


async def _nuovo(db, admin: User, *, role: UserRole = UserRole.operator) -> User:
    payload = UserCreate(
        username=f"prova-{uuid.uuid4().hex[:8]}",
        full_name="Utente Di Prova",
        role=role,
        initial_password="Password-Di-Prova-2026",
    )
    return await create_user(payload, db, user=admin)


async def test_elenco_delle_referenze_allineato_al_database(app_db_session) -> None:
    """`USER_REFERENCES` deve dire il vero, non la verità di quando fu scritto.

    Se qualcuno aggiunge una tabella che punta a `users` e non la aggiunge
    all'elenco, l'eliminazione fallirebbe con un errore di vincolo a metà
    operazione invece di scegliere la forma giusta. Meglio saperlo qui.
    """
    righe = await app_db_session.execute(text("""
        SELECT c.conrelid::regclass::text AS tabella,
               a.attname                  AS colonna,
               c.confdeltype::text        AS azione
        FROM pg_constraint c
        JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE c.contype = 'f' AND c.confrelid = 'users'::regclass
    """))
    # 'r' è ON DELETE RESTRICT: sono esattamente i vincoli che impediscono la
    # rimozione. 'c' (CASCADE) è `sessions`, che invece deve sparire con l'utente.
    trovate = {(tabella, colonna) for tabella, colonna, azione in righe if azione == "r"}
    assert trovate == set(USER_REFERENCES)


async def test_senza_storia_l_account_si_chiude_e_poi_si_toglie(app_db_session) -> None:
    admin = await _admin(app_db_session)
    utente = await _nuovo(app_db_session, admin)
    identificativo = utente.id

    chiusura = await delete_user(identificativo, app_db_session, user=admin)

    # Primo passo: l'account resta, chiuso e visibile fra gli eliminati. Prima
    # spariva qui, e chi aveva appena premuto «elimina» non trovava più niente
    # nemmeno chiedendo di vedere gli eliminati.
    assert chiusura.removed is False
    assert chiusura.purgeable is True
    assert chiusura.traces == {}
    chiuso = await app_db_session.get(User, identificativo)
    assert chiuso is not None and chiuso.deleted_at is not None

    rimozione = await purge_user(identificativo, app_db_session, user=admin)

    assert rimozione.removed is True
    assert await app_db_session.get(User, identificativo) is None


async def test_chi_ha_firmato_non_si_toglie_nemmeno_chiedendolo(app_db_session) -> None:
    admin = await _admin(app_db_session)
    utente = await _nuovo(app_db_session, admin)
    await write_audit(
        app_db_session, actor=utente, actor_username=utente.username,
        action="unit.update", details={},
    )
    await delete_user(utente.id, app_db_session, user=admin)

    # Il rifiuto arriva prima del database: senza, sarebbe un errore di vincolo
    # a metà operazione invece di una spiegazione.
    with pytest.raises(ValidationAppError):
        await purge_user(utente.id, app_db_session, user=admin)
    assert await app_db_session.get(User, utente.id) is not None


async def test_la_rimozione_definitiva_vuole_un_account_gia_chiuso(app_db_session) -> None:
    admin = await _admin(app_db_session)
    utente = await _nuovo(app_db_session, admin)

    with pytest.raises(ValidationAppError):
        await purge_user(utente.id, app_db_session, user=admin)


async def test_con_una_riga_di_registro_resta_come_account_chiuso(app_db_session) -> None:
    admin = await _admin(app_db_session)
    utente = await _nuovo(app_db_session, admin)
    # Basta un'operazione qualunque: l'audit la registra, e quella riga punta
    # all'utente con ON DELETE RESTRICT ed è protetta da trigger contro UPDATE
    # e DELETE.
    await write_audit(
        app_db_session, actor=utente, actor_username=utente.username,
        action="unit.update", details={},
    )

    esito = await delete_user(utente.id, app_db_session, user=admin)

    assert esito.removed is False
    assert esito.purgeable is False
    assert esito.traces["audit_log"] >= 1
    rimasto = await app_db_session.get(User, utente.id)
    assert rimasto is not None
    assert rimasto.deleted_at is not None
    assert rimasto.is_active is False
    # Senza password non si rientra nemmeno se qualcuno riattivasse la riga a
    # mano nel database.
    assert rimasto.password_hash is None


async def test_le_sessioni_aperte_vengono_revocate(app_db_session) -> None:
    admin = await _admin(app_db_session)
    utente = await _nuovo(app_db_session, admin)
    await write_audit(
        app_db_session, actor=utente, actor_username=utente.username,
        action="unit.update", details={},
    )
    from datetime import UTC, datetime, timedelta

    sessione = Session(
        user_id=utente.id, token_hash=uuid.uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(hours=8),
    )
    app_db_session.add(sessione)
    await app_db_session.flush()

    await delete_user(utente.id, app_db_session, user=admin)

    await app_db_session.refresh(sessione)
    assert sessione.revoked_at is not None


async def test_non_si_elimina_l_account_con_cui_si_e_entrati(app_db_session) -> None:
    admin = await _admin(app_db_session)
    with pytest.raises(ValidationAppError):
        await delete_user(admin.id, app_db_session, user=admin)


async def test_non_si_declassa_l_ultimo_amministratore(app_db_session) -> None:
    admin = await _admin(app_db_session)
    altri = await app_db_session.execute(
        select(User).where(
            User.role == UserRole.admin, User.is_active.is_(True),
            User.deleted_at.is_(None), User.id != admin.id,
        )
    )
    if altri.scalars().first() is not None:
        pytest.skip("C'è più di un amministratore attivo: il caso limite non si presenta.")

    with pytest.raises(ValidationAppError):
        await update_user(admin.id, UserUpdate(role=UserRole.viewer), app_db_session, user=admin)
    with pytest.raises(ValidationAppError):
        await update_user(admin.id, UserUpdate(is_active=False), app_db_session, user=admin)


async def test_il_nome_utente_chiuso_resta_riservato(app_db_session) -> None:
    admin = await _admin(app_db_session)
    utente = await _nuovo(app_db_session, admin)
    await write_audit(
        app_db_session, actor=utente, actor_username=utente.username,
        action="unit.update", details={},
    )
    await delete_user(utente.id, app_db_session, user=admin)

    # Riassegnare il nome a una persona diversa renderebbe illeggibile il
    # registro, dove le righe vecchie lo citano per nome.
    with pytest.raises(ValidationAppError):
        await create_user(
            UserCreate(
                username=utente.username, full_name="Un Altro",
                initial_password="Password-Di-Prova-2026",
            ),
            app_db_session, user=admin,
        )


async def test_un_account_chiuso_non_si_modifica(app_db_session) -> None:
    admin = await _admin(app_db_session)
    utente = await _nuovo(app_db_session, admin)
    await write_audit(
        app_db_session, actor=utente, actor_username=utente.username,
        action="unit.update", details={},
    )
    await delete_user(utente.id, app_db_session, user=admin)

    with pytest.raises(NotFoundError):
        await update_user(utente.id, UserUpdate(is_active=True), app_db_session, user=admin)


async def test_ripristino_riapre_con_una_password_nuova(app_db_session) -> None:
    admin = await _admin(app_db_session)
    utente = await _nuovo(app_db_session, admin)
    await write_audit(
        app_db_session, actor=utente, actor_username=utente.username,
        action="unit.update", details={},
    )
    await delete_user(utente.id, app_db_session, user=admin)

    esito = await restore_user(utente.id, app_db_session, user=admin)

    assert esito.temporary_password
    ripristinato = await app_db_session.get(User, utente.id)
    assert ripristinato.deleted_at is None
    assert ripristinato.is_active is True
    assert ripristinato.must_change_password is True


async def test_l_elenco_nasconde_gli_eliminati_salvo_richiesta(app_db_session) -> None:
    admin = await _admin(app_db_session)
    utente = await _nuovo(app_db_session, admin)
    await write_audit(
        app_db_session, actor=utente, actor_username=utente.username,
        action="unit.update", details={},
    )
    await delete_user(utente.id, app_db_session, user=admin)

    visibili = await list_users(app_db_session, page_size=200, user=admin)
    assert utente.id not in {riga.id for riga in visibili.items}

    tutti = await list_users(app_db_session, page_size=200, include_deleted=True, user=admin)
    assert utente.id in {riga.id for riga in tutti.items}
    # E l'elenco dice anche se quella riga si può ancora togliere del tutto:
    # è quello che decide se il pulsante compare.
    riga = next(riga for riga in tutti.items if riga.id == utente.id)
    assert riga.can_purge is False


async def test_l_elenco_segnala_chi_si_puo_ancora_togliere(app_db_session) -> None:
    admin = await _admin(app_db_session)
    utente = await _nuovo(app_db_session, admin)
    await delete_user(utente.id, app_db_session, user=admin)

    tutti = await list_users(app_db_session, page_size=200, include_deleted=True, user=admin)
    riga = next(riga for riga in tutti.items if riga.id == utente.id)
    assert riga.can_purge is True
