"""Conservazione del registro di controllo: dodici mesi, e non un giorno prima.

Il registro è append-only, e una conservazione a tempo è l'unica eccezione a
quella regola. Questi test provano l'eccezione dai due lati: che funzioni
dove deve, e che non si apra dove non deve — compreso il registro dei
movimenti, che non ha nessuna scadenza perché **è** la giacenza.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


async def _riga_audit(conn, quando: datetime) -> int:
    esito = await conn.execute(
        text(
            "INSERT INTO audit_log (ts, actor_username, action, entity_type, details) "
            "VALUES (:ts, 'prova', :azione, 'prova', CAST(:dettagli AS JSONB)) RETURNING id"
        ),
        {"ts": quando, "azione": f"prova.{uuid.uuid4().hex[:6]}", "dettagli": json.dumps({})},
    )
    return esito.scalar_one()


async def _pulisci(conn, giorni: int) -> int:
    """La stessa sequenza del lavoro notturno, dentro la transazione del test."""
    await conn.execute(text("SELECT set_config('netstock.pulizia_audit', 'in-corso', true)"))
    await conn.execute(
        text("SELECT set_config('netstock.audit_retention', :finestra, true)"),
        {"finestra": f"{giorni} days"},
    )
    esito = await conn.execute(
        text("DELETE FROM audit_log WHERE ts < now() - make_interval(days => :giorni)"),
        {"giorni": giorni},
    )
    return esito.rowcount or 0


async def test_una_riga_scaduta_si_cancella(superuser_connection) -> None:
    vecchia = await _riga_audit(superuser_connection, datetime.now(UTC) - timedelta(days=400))

    await _pulisci(superuser_connection, 365)

    resta = await superuser_connection.execute(
        text("SELECT count(*) FROM audit_log WHERE id = :id"), {"id": vecchia}
    )
    assert resta.scalar_one() == 0


async def test_una_riga_dentro_la_finestra_resta(superuser_connection) -> None:
    """Undici mesi non sono dodici: la pulizia non arrotonda."""
    recente = await _riga_audit(superuser_connection, datetime.now(UTC) - timedelta(days=330))

    await _pulisci(superuser_connection, 365)

    resta = await superuser_connection.execute(
        text("SELECT count(*) FROM audit_log WHERE id = :id"), {"id": recente}
    )
    assert resta.scalar_one() == 1


async def test_senza_dichiarare_la_pulizia_non_si_cancella_niente(superuser_connection) -> None:
    """Il varco non è «le righe vecchie si possono cancellare»: è «si possono
    cancellare dicendo che si sta facendo pulizia». Una `DELETE` qualunque,
    anche su una riga scadutissima, resta rifiutata."""
    vecchia = await _riga_audit(superuser_connection, datetime.now(UTC) - timedelta(days=1000))

    with pytest.raises(DBAPIError, match="append-only"):
        await superuser_connection.execute(
            text("DELETE FROM audit_log WHERE id = :id"), {"id": vecchia}
        )


async def test_la_pulizia_non_puo_cancellare_il_recente(superuser_connection) -> None:
    """Il caso che rende la regola una regola: dichiarare la pulizia non
    autorizza a cancellare quello che si vuole, ma solo ciò che è scaduto."""
    recente = await _riga_audit(superuser_connection, datetime.now(UTC) - timedelta(days=1))
    await superuser_connection.execute(
        text("SELECT set_config('netstock.pulizia_audit', 'in-corso', true)")
    )
    await superuser_connection.execute(
        text("SELECT set_config('netstock.audit_retention', '365 days', true)")
    )

    with pytest.raises(DBAPIError, match="append-only"):
        await superuser_connection.execute(
            text("DELETE FROM audit_log WHERE id = :id"), {"id": recente}
        )


async def test_modificare_una_riga_resta_impossibile(superuser_connection) -> None:
    """La conservazione riguarda la cancellazione. Riscrivere una riga del
    registro non è previsto da nessuna parte, nemmeno durante una pulizia."""
    riga = await _riga_audit(superuser_connection, datetime.now(UTC) - timedelta(days=1000))
    await superuser_connection.execute(
        text("SELECT set_config('netstock.pulizia_audit', 'in-corso', true)")
    )
    await superuser_connection.execute(
        text("SELECT set_config('netstock.audit_retention', '365 days', true)")
    )

    with pytest.raises(DBAPIError, match="append-only"):
        await superuser_connection.execute(
            text("UPDATE audit_log SET action = 'manomessa' WHERE id = :id"), {"id": riga}
        )


async def test_il_registro_dei_movimenti_non_scade(superuser_connection) -> None:
    """La regressione che conta più di tutte: il ledger non deve aver preso la
    scorciatoia dell'audit. Un movimento di tre anni fa è ancora la ragione per
    cui oggi ci sono quei pezzi su quello scaffale, e non è un registro di
    quello che è stato fatto: è la giacenza."""
    # Un movimento vero, creato qui: senza righe la cancellazione non
    # farebbe scattare nessun trigger e il test passerebbe senza provare
    # niente.
    articolo = (await superuser_connection.execute(text(
        "INSERT INTO catalog_items (vendor_id, category_id, part_number, name, is_serialized, uom) "
        "SELECT v.id, c.id, :pn, 'articolo di prova', false, 'PZ' "
        "FROM vendors v, categories c LIMIT 1 RETURNING id"
    ), {"pn": f"PROVA-{uuid.uuid4().hex[:8]}"})).scalar_one()
    movimento = (await superuser_connection.execute(text(
        "INSERT INTO stock_movements "
        "(occurred_at, type, catalog_item_id, quantity, condition, location_to_id, performed_by) "
        "SELECT now(), 'receipt', :articolo, 1, 'new', l.id, u.id "
        "FROM locations l, users u LIMIT 1 RETURNING id"
    ), {"articolo": articolo})).scalar_one()

    await superuser_connection.execute(
        text("SELECT set_config('netstock.pulizia_audit', 'in-corso', true)")
    )
    await superuser_connection.execute(
        text("SELECT set_config('netstock.audit_retention', '1 second', true)")
    )

    with pytest.raises(DBAPIError, match="append-only"):
        await superuser_connection.execute(
            text("DELETE FROM stock_movements WHERE id = :id"), {"id": movimento}
        )


async def test_il_lavoro_notturno_fa_davvero_pulizia(superuser_connection) -> None:
    """Prova la funzione che gira ogni notte, non una sua imitazione.

    I test qui sopra ripetono la sequenza del lavoro; questo esegue proprio
    quella funzione. La differenza non è teorica: la prima versione usava
    `SET LOCAL` con un parametro, che PostgreSQL non accetta, e sarebbe
    fallita ogni notte alle 03:10 senza che nessuno se ne accorgesse.
    """
    from app.main import _job_purge_audit_log

    vecchia = await _riga_audit(superuser_connection, datetime.now(UTC) - timedelta(days=500))
    recente = await _riga_audit(superuser_connection, datetime.now(UTC) - timedelta(days=5))
    # Il lavoro apre una connessione sua e conferma: quello che deve trovare
    # dev'essere già scritto.
    await superuser_connection.commit()

    await _job_purge_audit_log()

    rimaste = await superuser_connection.execute(
        text("SELECT id FROM audit_log WHERE id = ANY(:ids)"), {"ids": [vecchia, recente]}
    )
    assert [r.id for r in rimaste] == [recente]
    tracce = await superuser_connection.execute(
        text("SELECT count(*) FROM audit_log WHERE action = 'audit.prune'")
    )
    assert tracce.scalar_one() >= 1  # la pulizia si annota nel registro stesso
