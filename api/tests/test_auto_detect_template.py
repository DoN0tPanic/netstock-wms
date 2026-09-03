import pytest

from app.services.extraction import pipeline
from app.services.extraction.schemas import FieldSpec, TemplateSpec

_DDT_TEXT = "BOLLA DI CONSEGNA\nN. DDT: 99887/2026\nData: 27/08/2026\n"


def _device_label_template(priority: int = 100) -> TemplateSpec:
    return TemplateSpec(
        id="device",
        name="Cisco device label",
        doc_type="device_label",
        priority=priority,
        fields=[
            FieldSpec(
                name="serial_number",
                target="unit.serial_number",
                regex=r"^[A-Z]{3}[0-9]{4}[A-Z0-9]{4}$",
                keywords=["S/N", "SERIAL"],
                required=True,
            ),
        ],
    )


def _delivery_note_template(priority: int = 100) -> TemplateSpec:
    return TemplateSpec(
        id="ddt",
        name="Generico / bolla DDT",
        doc_type="delivery_note",
        priority=priority,
        fields=[
            FieldSpec(
                name="ddt_number",
                target="delivery_note.number",
                regex=r"[0-9]{1,10}(/[0-9]{2,4})?",
                keywords=["DDT", "N."],
                required=True,
            ),
            FieldSpec(
                name="ddt_date",
                target="delivery_note.note_date",
                regex=r"[0-3]?[0-9][/\-][0-1]?[0-9][/\-][0-9]{2,4}",
                keywords=["DATA"],
                required=True,
            ),
        ],
    )


@pytest.fixture(autouse=True)
def _no_barcodes(monkeypatch):
    monkeypatch.setattr(pipeline, "decode_barcodes", lambda image_bytes: [])


async def test_picks_the_template_that_actually_resolves_its_required_fields(monkeypatch) -> None:
    # A plain paper delivery note has no barcode at all — the old
    # barcode-only detector fell back to an arbitrary template in this
    # case. The correct template here is the one whose required fields the
    # OCR text actually satisfies.
    monkeypatch.setattr(pipeline, "run_ocr", lambda image_bytes, doc_type: _DDT_TEXT)

    device = _device_label_template()
    ddt = _delivery_note_template()

    chosen = await pipeline.auto_detect_template([device, ddt], [b"fake-image"])

    assert chosen is not None
    assert chosen.id == "ddt"


async def test_ties_are_broken_by_priority(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline, "run_ocr", lambda image_bytes, doc_type: "no matching fields at all"
    )

    low = _delivery_note_template(priority=10)
    low.id = "low-priority"
    high = _delivery_note_template(priority=200)
    high.id = "high-priority"

    chosen = await pipeline.auto_detect_template([low, high], [b"fake-image"])

    assert chosen is not None
    assert chosen.id == "high-priority"


async def test_returns_none_for_empty_template_list() -> None:
    assert await pipeline.auto_detect_template([], [b"fake-image"]) is None
