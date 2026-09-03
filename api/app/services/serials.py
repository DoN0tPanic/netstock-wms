import re

_PREFIXES_TO_STRIP = ("SN:", "S/N", "SERIAL:", "SN ", "S/N:", "SERIALE:")

MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}[:\-.]?){5}[0-9A-Fa-f]{2}$")

KNOWN_VENDOR_PATTERNS: dict[str, str] = {
    "CISCO": r"^[A-Z]{3}[0-9]{4}[A-Z0-9]{4}$",
    "CISCO_ALT": r"^[A-Z]{3}[0-9]{2}[0-9]{2}[0-9A-Z]{4,5}$",
    "MERAKI": r"^Q[0-9A-Z]{3}-[0-9A-Z]{4}-[0-9A-Z]{4}$",
    "PALOALTO": r"^[0-9]{12,15}$",
}


def normalize_serial(raw: str) -> str:
    value = raw.strip().upper()
    for prefix in _PREFIXES_TO_STRIP:
        if value.startswith(prefix.upper()):
            value = value[len(prefix) :].strip()
    value = re.sub(r"\s+", "", value)
    return value


def normalize_mac(raw: str) -> str:
    value = raw.strip().upper()
    value = re.sub(r"[^0-9A-F]", "", value)
    return ":".join(value[i : i + 2] for i in range(0, len(value), 2))


def matches_pattern(serial: str, pattern: str | None) -> bool:
    if not pattern:
        return True
    try:
        return re.match(pattern, serial) is not None
    except re.error:
        return True
