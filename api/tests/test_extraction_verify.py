from app.services.extraction.rules import extract_field_from_text
from app.services.extraction.schemas import FieldSpec
from app.services.extraction.verify import is_verifiable


def test_verifiable_value_present_in_source() -> None:
    source = "Cisco Systems\nPID: C9200L-24P-4G-E\nSN: ZZO0000TEST\nMADE IN CHINA"
    assert is_verifiable("ZZO0000TEST", source) is True


def test_verifiable_value_with_minor_ocr_noise() -> None:
    # The letter 'O' misread as the digit '0' — still similar enough.
    source = "S/N ZZ00000TEST"
    assert is_verifiable("ZZO0000TEST", source) is True


def test_hallucinated_value_is_rejected() -> None:
    source = "Cisco Systems\nPID: C9200L-24P-4G-E\nMADE IN CHINA"
    assert is_verifiable("ZZO9999TEST", source) is False


def test_empty_value_never_verifiable() -> None:
    assert is_verifiable("", "some source text") is False


def test_rules_apply_ocr_fixes_only_when_pattern_matches_after_fix() -> None:
    spec = FieldSpec(
        name="serial_number",
        target="unit.serial_number",
        regex=r"^[A-Z]{3}[0-9]{4}[A-Z0-9]{4}$",
        keywords=["S/N"],
        keyword_window=20,
        ocr_fixes=True,
        required=True,
    )
    # OCR misread the digit '0' as letter 'O' in ZZO0000 -> ZZO000O.
    text = "LABEL S/N ZZO000OTEST END"
    candidate = extract_field_from_text(text, spec)
    assert candidate is not None
    assert candidate.value == "ZZO0000TEST"
    assert candidate.corrected is True


def test_rules_keyword_match_has_higher_confidence_than_bare_regex() -> None:
    spec = FieldSpec(
        name="serial_number",
        target="unit.serial_number",
        regex=r"^[A-Z]{3}[0-9]{4}[A-Z0-9]{4}$",
        keywords=["S/N"],
        keyword_window=20,
        required=True,
    )
    with_keyword = extract_field_from_text("S/N ZZO0000TEST", spec)
    without_keyword = extract_field_from_text("random text ZZO0000TEST noise", spec)
    assert with_keyword is not None and with_keyword.confidence.value == "medium"
    assert without_keyword is not None and without_keyword.confidence.value == "low"
