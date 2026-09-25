"""Una bolla chiusa si può riaprire, per collegarle altra merce.

Una bolla si chiude da sola appena tutte le righe risultano complete, e da
chiusa non accetta più né righe né ricezioni. Ma la merce vera non arriva
sempre tutta insieme: un secondo collo con lo stesso numero di bolla non aveva
nessun posto dove andare — la bolla non compariva più in nessun elenco.
"""

import uuid
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import select

from app.api.v1.delivery_notes import add_delivery_note_line, reopen_delivery_note
from app.exceptions import ValidationAppError
from app.models.audit import AuditLog
from app.models.catalog import CatalogItem, Category, Supplier, Vendor
from app.models.delivery import DeliveryNote
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.delivery import DeliveryNoteCloseRequest, DeliveryNoteLineCreate


@dataclass
class _Attore:
    id: uuid.UUID
    username: str
    role: UserRole


async def _semina(db, chiusa: bool) -> tuple[DeliveryNote, _Attore, CatalogItem]:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    fornitore = (await db.execute(select(Supplier).limit(1))).scalar_one_or_none()
    if fornitore is None:
        fornitore = Supplier(name=f"Fornitore di prova {uuid.uuid4().hex[:6]}")
        db.add(fornitore)
        await db.flush()

    unico = uuid.uuid4().hex[:8].upper()
    articolo = CatalogItem(
        vendor_id=vendor.id,
        category_id=category.id,
        part_number=f"RIAP-{unico}",
        name="Articolo per la prova di riapertura",
        is_serialized=False,
    )
    db.add(articolo)
    bolla = DeliveryNote(
        number=f"DDT-RIAP-{unico}",
        note_date=date(2026, 3, 4),
        supplier_id=fornitore.id,
        received_by=admin.id,
        is_closed=chiusa,
    )
    db.add_all([articolo, bolla])
    await db.flush()
    return bolla, _Attore(id=admin.id, username=admin.username, role=UserRole.operator), articolo


async def test_riaprire_rimette_la_bolla_fra_quelle_aperte(app_db_session) -> None:
    bolla, attore, _ = await _semina(app_db_session, chiusa=True)

    riaperta = await reopen_delivery_note(
        note_id=bolla.id,
        payload=DeliveryNoteCloseRequest(reason="arrivato un secondo collo con la stessa bolla"),
        db=app_db_session,
        user=attore,  # type: ignore[arg-type]
    )

    assert riaperta.is_closed is False


async def test_dopo_la_riapertura_si_possono_aggiungere_righe(app_db_session) -> None:
    # È il punto di tutto: riaprire senza poter collegare merce non servirebbe.
    bolla, attore, articolo = await _semina(app_db_session, chiusa=True)
    with pytest.raises(ValidationAppError):
        await add_delivery_note_line(
            note_id=bolla.id,
            payload=DeliveryNoteLineCreate(catalog_item_id=articolo.id, qty_expected=2),
            db=app_db_session,
            user=attore,  # type: ignore[arg-type]
        )

    await reopen_delivery_note(
        note_id=bolla.id,
        payload=DeliveryNoteCloseRequest(reason="due pezzi in più rispetto al dichiarato"),
        db=app_db_session,
        user=attore,  # type: ignore[arg-type]
    )

    riga = await add_delivery_note_line(
        note_id=bolla.id,
        payload=DeliveryNoteLineCreate(catalog_item_id=articolo.id, qty_expected=2),
        db=app_db_session,
        user=attore,  # type: ignore[arg-type]
    )
    assert riga.delivery_note_id == bolla.id


async def test_la_riapertura_finisce_nel_registro_con_il_motivo(app_db_session) -> None:
    bolla, attore, _ = await _semina(app_db_session, chiusa=True)
    motivo = "secondo collo arrivato il giorno dopo"

    await reopen_delivery_note(
        note_id=bolla.id,
        payload=DeliveryNoteCloseRequest(reason=motivo),
        db=app_db_session,
        user=attore,  # type: ignore[arg-type]
    )
    await app_db_session.flush()

    voce = (
        await app_db_session.execute(
            select(AuditLog)
            .where(AuditLog.action == "delivery_note.reopen")
            .where(AuditLog.entity_id == str(bolla.id))
        )
    ).scalar_one()
    assert voce.details["reason"] == motivo
    assert voce.actor_username == attore.username


@pytest.mark.parametrize(
    # «sbagliata» sono nove caratteri: uno sotto la soglia, che è il
    # confine dove un controllo scritto male passa senza accorgersene.
    "motivo", ["", "   ", "corto", "sbagliata", "         x"]
)
async def test_serve_un_motivo_vero(app_db_session, motivo: str) -> None:
    # Senza, «riaperta» nel registro non spiegherebbe niente a chi la rilegge.
    bolla, attore, _ = await _semina(app_db_session, chiusa=True)

    with pytest.raises(ValidationAppError):
        await reopen_delivery_note(
            note_id=bolla.id,
            payload=DeliveryNoteCloseRequest(reason=motivo),
            db=app_db_session,
            user=attore,  # type: ignore[arg-type]
        )


async def test_una_bolla_gia_aperta_non_si_riapre(app_db_session) -> None:
    bolla, attore, _ = await _semina(app_db_session, chiusa=False)

    with pytest.raises(ValidationAppError):
        await reopen_delivery_note(
            note_id=bolla.id,
            payload=DeliveryNoteCloseRequest(reason="motivo abbastanza lungo da passare"),
            db=app_db_session,
            user=attore,  # type: ignore[arg-type]
        )
