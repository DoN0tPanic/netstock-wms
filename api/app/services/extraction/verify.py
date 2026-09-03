import re
from difflib import SequenceMatcher


def _normalize(text: str) -> str:
    return re.sub(r"[\s\-]+", "", text.upper())


def is_verifiable(value: str, source_text: str, threshold: float = 0.9) -> bool:
    """Anti-hallucination check (§7.2 stage 5).

    The LLM value must appear, after normalization, literally in the OCR
    text or a barcode payload, with normalized-Levenshtein-like similarity
    over a sliding window >= threshold. A value that fails is discarded, not
    shown at low confidence: an invented serial is worse than an empty field.
    """
    needle = _normalize(value)
    if not needle:
        return False

    haystack = _normalize(source_text)
    if needle in haystack:
        return True

    window_size = len(needle)
    if window_size == 0 or len(haystack) < window_size:
        return SequenceMatcher(None, needle, haystack).ratio() >= threshold

    # Step 1: OCR text for a single label/DDT is at most a few KB, and values
    # are short (serials, part numbers), so an exhaustive scan is cheap. A
    # coarser step could skip the one alignment where a short value actually
    # matches, turning a real match into a false "hallucination" rejection —
    # which would throw away a correct value the operator could have used.
    best_ratio = 0.0
    for start in range(0, len(haystack) - window_size + 1):
        window = haystack[start : start + window_size]
        ratio = SequenceMatcher(None, needle, window).ratio()
        best_ratio = max(best_ratio, ratio)
        if best_ratio >= threshold:
            return True
    return best_ratio >= threshold
