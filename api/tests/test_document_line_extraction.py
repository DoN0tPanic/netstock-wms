import uuid
from decimal import Decimal

from app.services.extraction.document_lines import CatalogItemRef, extract_document_lines

_CISCO_PATTERN = r"^[A-Z]{3}[0-9]{4}[A-Z0-9]{4}$"


def _item(part_number: str, is_serialized: bool, pattern: str | None = None) -> CatalogItemRef:
    return CatalogItemRef(
        id=uuid.uuid4(),
        part_number=part_number,
        name=part_number,
        vendor_code="CISCO",
        is_serialized=is_serialized,
        serial_pattern=pattern,
    )


def test_groups_serials_to_the_correct_preceding_model() -> None:
    switch = _item("C9200L-24P-4G-E", True, _CISCO_PATTERN)
    ap = _item("C9300-48P-A", True, _CISCO_PATTERN)
    text = (
        "Articolo: C9200L-24P-4G-E\nSeriali:\nZZO0002TEST\nZZO0003TEST\n"
        "Articolo: C9300-48P-A\nSeriali:\nZZO0005TEST\n"
    )

    lines, unassigned = extract_document_lines(text, [switch, ap])

    assert unassigned == []
    assert len(lines) == 2
    assert lines[0].catalog_item.part_number == "C9200L-24P-4G-E"
    assert sorted(lines[0].serials) == ["ZZO0002TEST", "ZZO0003TEST"]
    assert lines[0].quantity == 2
    assert lines[1].catalog_item.part_number == "C9300-48P-A"
    assert lines[1].serials == ["ZZO0005TEST"]


def test_non_serialized_line_gets_quantity_not_serials() -> None:
    cable = _item("PATCH-CAT6-1M", False)
    text = "Articolo: PATCH-CAT6-1M\nQta: 50 PZ\n"

    lines, unassigned = extract_document_lines(text, [cable])

    assert unassigned == []
    assert len(lines) == 1
    assert lines[0].serials == []
    assert lines[0].quantity == 50


def test_serial_never_invented_only_literal_ocr_substrings_returned() -> None:
    switch = _item("C9200L-24P-4G-E", True, _CISCO_PATTERN)
    text = "Articolo: C9200L-24P-4G-E\nSeriali:\nZZO0002TEST\nNOTASERIALATALL\n"

    lines, unassigned = extract_document_lines(text, [switch])

    assert lines[0].serials == ["ZZO0002TEST"]
    assert "NOTASERIALATALL" not in lines[0].serials
    assert "NOTASERIALATALL" not in unassigned  # doesn't match any known pattern at all


def test_ocr_confusable_digit_letter_is_corrected_like_single_field_extraction() -> None:
    switch = _item("C9200L-24P-4G-E", True, _CISCO_PATTERN)
    # 'O' misread as '0' by the OCR, same confusion class as rules.py handles.
    text = "Articolo: C9200L-24P-4G-E\nSeriali:\nZZ00005TEST\n"

    lines, unassigned = extract_document_lines(text, [switch])

    assert unassigned == []
    assert lines[0].serials == ["ZZO0005TEST"]


def test_serials_before_any_model_are_unassigned_not_dropped() -> None:
    switch = _item("C9200L-24P-4G-E", True, _CISCO_PATTERN)
    text = "ZZO0002TEST\nArticolo: C9200L-24P-4G-E\n"

    lines, unassigned = extract_document_lines(text, [switch])

    assert unassigned == ["ZZO0002TEST"]
    assert lines[0].serials == []


def test_no_recognized_model_returns_no_lines_and_pool_of_serials() -> None:
    switch = _item("C9200L-24P-4G-E", True, _CISCO_PATTERN)
    text = "Documento senza alcun modello riconoscibile.\nZZO0002TEST\n"

    lines, unassigned = extract_document_lines(text, [switch])

    assert lines == []
    assert unassigned == ["ZZO0002TEST"]


def test_non_serialized_part_number_with_ocr_misread_digit_is_still_found() -> None:
    # '1' misread as 'I' by the OCR — the real-world case flagged for
    # non-serialized items (e.g. power cords) that have no serial to fall
    # back on, so the part number itself must tolerate this.
    cable = _item("PATCH-CAT6-1M", False)
    text = "Articolo: PATCH-CAT6-IM\nQta: 30 PZ\n"

    lines, unassigned = extract_document_lines(text, [cable])

    assert unassigned == []
    assert len(lines) == 1
    assert lines[0].catalog_item.part_number == "PATCH-CAT6-1M"
    assert lines[0].quantity == 30


def test_a_longer_serial_is_not_chopped_to_fit_the_pattern() -> None:
    """Regressione: il pattern Cisco descrive 11 caratteri, e cercato senza
    confini dentro un seriale da 12 ne agganciava 11 buttando via il primo.

    `ZZQP4475EQ50` diventava `ZZQP4475EQ50`, e l'operatore se lo ritrovava
    proposto così — un carattere di differenza, dentro un registro append-only
    che non si corregge. Un seriale che non corrisponde al pattern deve
    risultare **assente**, mai accorciato finché non ci sta.
    """
    switch = _item("C9200L-24P-4G-E", True, _CISCO_PATTERN)
    text = "Articolo: C9200L-24P-4G-E\nSN: ZZQP4475EQ50\nSN: ZZQP4476FR60\n"

    lines, unassigned = extract_document_lines(text, [switch])

    trovati = [serial for line in lines for serial in line.serials] + unassigned
    assert trovati == []
    assert "ZQP4475EQ50" not in trovati
    assert "ZQP4476FR60" not in trovati


def test_a_serial_embedded_in_a_line_is_still_found_whole() -> None:
    """Il confine di token non deve impedire di trovare un seriale che sta in
    mezzo a una riga insieme ad altro testo."""
    switch = _item("C9200L-24P-4G-E", True, _CISCO_PATTERN)
    text = "C9200L-24P-4G-E   SN: ZZO0002TEST, SN: ZZO0003TEST   collo 3\n"

    lines, _ = extract_document_lines(text, [switch])

    assert lines[0].serials == ["ZZO0002TEST", "ZZO0003TEST"]


def test_a_number_inside_the_product_name_is_not_a_quantity() -> None:
    """Regressione: la quantità veniva indovinata prendendo il primo numero
    vicino al codice, e su una riga reale leggeva `9200` da "SWITCH 9200",
    cioè dal nome del modello. L'operatore si ritrovava proposto di caricare
    novemiladuecento moduli invece di otto.
    """
    modulo = _item("SW-NM-4X", False)
    text = "4 8 8 A12BC34 SWITCH 9200 4 X 10G MODULO DI RETE SW-NM-4X=\n"

    lines, _ = extract_document_lines(text, [modulo])

    assert lines[0].quantity is None


def test_a_quantity_introduced_by_a_keyword_is_read() -> None:
    cavo = _item("CAB-TA-EU", False)
    text = "Articolo CAB-TA-EU= QTA 9 PZ\n"

    lines, _ = extract_document_lines(text, [cavo])

    assert lines[0].quantity == Decimal(9)
