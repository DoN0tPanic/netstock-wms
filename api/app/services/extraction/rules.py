import re

from app.services.extraction.schemas import Confidence, FieldCandidate, FieldSpec

_OCR_FIX_PAIRS = [("O", "0"), ("I", "1"), ("S", "5"), ("B", "8"), ("Z", "2")]
_LETTERS_CONFUSED_FOR_DIGITS = "OISBZ"


# Caratteri che possono far parte di un codice. Un match che comincia o
# finisce con uno di questi accanto sta tagliando un codice più lungo a metà.
_TOKEN_CHARS = "A-Za-z0-9-"


def _unanchored(pattern: str) -> str:
    """Toglie `^`/`$` dal pattern per poterlo cercare dentro un testo più
    ampio, sostituendoli con un confine di token.

    I pattern dei template descrivono la *forma di un valore isolato* (per
    esempio `^[A-Z]{3}[0-9]{4}[A-Z0-9]{4}$`) e vengono usati, ancorati, anche
    per validare un valore già estratto (`_try_ocr_fixes`,
    `services.serials.matches_pattern`). Cercare quel pattern ancorato dentro
    un blocco di OCR non troverebbe mai niente, perché `^`/`$` pretendono che
    sia l'intera stringa cercata a soddisfarlo.

    Ma toglierli e basta non basta, ed è un errore che costa caro: il pattern
    Cisco qui sopra descrive 11 caratteri, e cercato senza confini dentro un
    seriale da 12 ne aggancia 11 scartando il primo — `ZZQP4475EQ50` diventava
    `ZZQP4475EQ50`. Un seriale sbagliato di un carattere finisce nel registro
    append-only e da lì non si toglie più. I lookaround impediscono al match di
    cominciare o finire in mezzo a un codice: o combacia con l'intero token, o
    non è quello che stiamo cercando.
    """
    if pattern.startswith("^"):
        pattern = pattern[1:]
    if pattern.endswith("$") and not pattern.endswith(r"\$"):
        pattern = pattern[:-1]
    return f"(?<![{_TOKEN_CHARS}])(?:{pattern})(?![{_TOKEN_CHARS}])"


def _loosen_for_ocr(pattern: str) -> str:
    """Widens `[0-9]` and `[A-Z]` character classes to also accept the
    letters/digits OCR commonly confuses them with (§7.2 stage 3: O/0, I/1,
    S/5, B/8, Z/2), so a candidate whose *shape* only matches after fixing a
    misread character can still be located in the text. `_try_ocr_fixes`
    then decides, against the true pattern, whether a fix actually resolves
    it — this function only widens the search, it never accepts a value.
    """
    pattern = pattern.replace("[0-9]", f"[0-9{_LETTERS_CONFUSED_FOR_DIGITS}]")
    pattern = pattern.replace("[A-Z]", "[A-Z0-9]")
    return pattern


def _try_ocr_fixes(candidate: str, pattern: str) -> tuple[str, bool]:
    if re.match(pattern, candidate):
        return candidate, False

    chars = list(candidate)
    for i, ch in enumerate(chars):
        for wrong, right in _OCR_FIX_PAIRS + [(r, w) for w, r in _OCR_FIX_PAIRS]:
            if ch == wrong:
                attempt = chars.copy()
                attempt[i] = right
                fixed = "".join(attempt)
                if re.match(pattern, fixed):
                    return fixed, True
    return candidate, False


def _find_candidate(window: str, spec: FieldSpec) -> tuple[str, bool] | None:
    """Finds a value in `window` matching `spec.regex`, applying OCR-fix
    correction when `spec.ocr_fixes` is set and the exact pattern doesn't
    match anywhere but a plausibly-misread shape does. Returns
    (value, corrected) or None.
    """
    strict_pattern = _unanchored(spec.regex)  # type: ignore[arg-type]
    exact_match = re.search(strict_pattern, window)
    if exact_match:
        return exact_match.group(0), False

    if not spec.ocr_fixes:
        return None

    loose_pattern = _unanchored(_loosen_for_ocr(spec.regex))  # type: ignore[arg-type]
    for loose_match in re.finditer(loose_pattern, window):
        candidate = loose_match.group(0)
        fixed, corrected = _try_ocr_fixes(candidate, spec.regex)  # type: ignore[arg-type]
        if corrected:
            return fixed, True
    return None


def extract_field_from_text(text: str, spec: FieldSpec) -> FieldCandidate | None:
    if not spec.regex:
        return None

    upper_text = text.upper()

    for keyword in spec.keywords:
        keyword_upper = keyword.upper()
        for match in re.finditer(re.escape(keyword_upper), upper_text):
            window_start = match.end()
            window = upper_text[window_start : window_start + spec.keyword_window]
            found = _find_candidate(window, spec)
            if found:
                value, corrected = found
                return FieldCandidate(
                    field=spec.name,
                    value=value,
                    confidence=Confidence.medium,
                    source="ocr_keyword",
                    corrected=corrected,
                )

    found = _find_candidate(upper_text, spec)
    if found:
        value, corrected = found
        return FieldCandidate(
            field=spec.name,
            value=value,
            confidence=Confidence.low,
            source="ocr_regex",
            corrected=corrected,
        )

    return None


def extract_all_fields(text: str, field_specs: list[FieldSpec]) -> list[FieldCandidate]:
    candidates = []
    for spec in field_specs:
        candidate = extract_field_from_text(text, spec)
        if candidate is not None:
            candidates.append(candidate)
    return candidates
