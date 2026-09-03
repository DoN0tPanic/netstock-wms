import uuid

from sqlalchemy import select

from app.api.v1.extraction import _match_catalog_item
from app.models.catalog import CatalogItem, Category, Vendor
from app.services.extraction.schemas import Confidence, ExtractionOutcome, FieldCandidate


def _outcome_with_part_number(value: str) -> ExtractionOutcome:
    return ExtractionOutcome(
        fields={
            "part_number": FieldCandidate(
                field="part_number", value=value, confidence=Confidence.high, source="barcode"
            )
        },
        conflicts={},
        raw_barcodes=[],
        raw_ocr_text="",
        engine="barcode",
        template_id=None,
        template_name=None,
        duration_ms=1,
    )


async def _seed_catalog_item(db, part_number: str) -> CatalogItem:
    vendor = (await db.execute(select(Vendor).limit(1))).scalar_one()
    category = (await db.execute(select(Category).limit(1))).scalar_one()
    item = CatalogItem(
        vendor_id=vendor.id, category_id=category.id, part_number=part_number, name="Test match"
    )
    db.add(item)
    await db.flush()
    return item


async def test_exact_part_number_match(app_db_session) -> None:
    unique = uuid.uuid4().hex[:8].upper()
    part_number = f"MATCH-EXACT-{unique}"
    item = await _seed_catalog_item(app_db_session, part_number)

    match = await _match_catalog_item(app_db_session, _outcome_with_part_number(part_number))

    assert match is not None
    assert match.id == item.id
    assert match.part_number == part_number


async def test_no_match_returns_none(app_db_session) -> None:
    match = await _match_catalog_item(
        app_db_session, _outcome_with_part_number("TOTALLY-UNRELATED-STRING-XYZ")
    )
    assert match is None


async def test_missing_part_number_field_returns_none(app_db_session) -> None:
    outcome = ExtractionOutcome(
        fields={},
        conflicts={},
        raw_barcodes=[],
        raw_ocr_text="",
        engine="barcode",
        template_id=None,
        template_name=None,
        duration_ms=1,
    )
    match = await _match_catalog_item(app_db_session, outcome)
    assert match is None
