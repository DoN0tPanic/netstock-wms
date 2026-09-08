"""Le righe della bolla portano il modello scritto, non solo il suo id.

Prima la scheda della bolla scaricava l'intero catalogo nel browser per
tradurre tre righe: su ottomila articoli erano quarantuno richieste in fila,
perché l'elenco arriva a pagine da duecento.
"""

import uuid
from datetime import date

from sqlalchemy import event, select

from app.api.v1.delivery_notes import get_delivery_note
from app.models.catalog import CatalogItem, Category, Supplier, Vendor
from app.models.delivery import DeliveryNote, DeliveryNoteLine
from app.models.enums import ItemCondition, UserRole
from app.models.users import User


class _FakeUser:
    role = UserRole.viewer


async def _semina_bolla(db, quante_righe: int) -> DeliveryNote:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    supplier = (await db.execute(select(Supplier).limit(1))).scalar_one_or_none()
    if supplier is None:
        supplier = Supplier(name=f"Fornitore di prova {uuid.uuid4().hex[:6]}")
        db.add(supplier)
        await db.flush()
    admin = (await db.execute(select(User).limit(1))).scalar_one()
    unico = uuid.uuid4().hex[:8].upper()

    articoli = [
        CatalogItem(
            vendor_id=vendor.id,
            category_id=category.id,
            part_number=f"BOLLA-{unico}-{indice}",
            name=f"Articolo di prova {indice}",
            is_serialized=False,
        )
        for indice in range(quante_righe)
    ]
    db.add_all(articoli)
    await db.flush()

    bolla = DeliveryNote(
        number=f"DDT-{unico}",
        note_date=date(2026, 1, 15),
        supplier_id=supplier.id,
        received_by=admin.id,
    )
    db.add(bolla)
    await db.flush()
    db.add_all(
        [
            DeliveryNoteLine(
                delivery_note_id=bolla.id,
                line_number=indice + 1,
                catalog_item_id=articolo.id,
                qty_expected=3,
                condition=ItemCondition.new,
            )
            for indice, articolo in enumerate(articoli)
        ]
    )
    await db.flush()
    return bolla


async def test_le_righe_portano_part_number_e_nome(app_db_session) -> None:
    bolla = await _semina_bolla(app_db_session, 3)

    letta = await get_delivery_note(note_id=bolla.id, db=app_db_session, user=_FakeUser())

    assert len(letta.lines) == 3
    for riga in letta.lines:
        assert riga.part_number and riga.part_number.startswith("BOLLA-")
        assert riga.catalog_item_name and riga.catalog_item_name.startswith("Articolo di prova")


async def test_un_solo_giro_al_catalogo_qualunque_sia_il_numero_di_righe(app_db_session) -> None:
    # Il punto della modifica: il costo non deve crescere con le righe, e non
    # deve dipendere da quanto è grande il catalogo.
    bolla = await _semina_bolla(app_db_session, 6)

    interrogazioni: list[str] = []
    motore = app_db_session.get_bind()

    def registra(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ARG001
        if "catalog_items" in statement and statement.lstrip().upper().startswith("SELECT"):
            interrogazioni.append(statement)

    event.listen(motore, "before_cursor_execute", registra)
    try:
        letta = await get_delivery_note(note_id=bolla.id, db=app_db_session, user=_FakeUser())
    finally:
        event.remove(motore, "before_cursor_execute", registra)

    assert len(letta.lines) == 6
    assert all(riga.part_number for riga in letta.lines)
    assert len(interrogazioni) == 1, interrogazioni
