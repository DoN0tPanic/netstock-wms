import pytest

from app.services.serials import matches_pattern, normalize_mac, normalize_serial


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("zzo0000test", "ZZO0000TEST"),
        ("SN: ZZO0000TEST", "ZZO0000TEST"),
        ("S/N ZZO0000TEST", "ZZO0000TEST"),
        ("  ZZO0000TEST  ", "ZZO0000TEST"),
        ("SERIAL: Q2QN-9J8L-SLPD", "Q2QN-9J8L-SLPD"),
    ],
)
def test_normalize_serial(raw: str, expected: str) -> None:
    assert normalize_serial(raw) == expected


def test_normalize_mac() -> None:
    assert normalize_mac("e0:cb:bc:11:22:33") == "E0:CB:BC:11:22:33"
    assert normalize_mac("e0-cb-bc-11-22-33") == "E0:CB:BC:11:22:33"
    assert normalize_mac("e0cbbc112233") == "E0:CB:BC:11:22:33"


def test_matches_pattern_cisco() -> None:
    cisco_pattern = r"^[A-Z]{3}[0-9]{4}[A-Z0-9]{4}$"
    assert matches_pattern("ZZO0000TEST", cisco_pattern) is True
    assert matches_pattern("NOTASERIAL", cisco_pattern) is False


def test_matches_pattern_no_pattern_always_true() -> None:
    assert matches_pattern("anything", None) is True
