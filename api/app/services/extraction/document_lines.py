"""Multi-line extraction for a whole delivery note photo (§7, extended).

Deliberately deterministic, no LLM: a delivery note lists several models,
each often followed by a block of serials. Inventing an LLM step here would
mean asking a language model to *generate* serial numbers into a warehouse
ledger that never gets cleaned up — exactly the failure mode §7.2 stage 5
guards against for single-field extraction. Instead this reuses the same
building blocks already trusted elsewhere: each catalog item's own
`serial_pattern` (with the same OCR-confusion tolerance as single-field
extraction) to find every serial actually printed in the OCR text, and a
literal/fuzzy scan for part numbers against the real catalog. Every serial
in the output is a literal substring of the OCR text — never something a
model produced. Grouping (which serial belongs to which model) is done by
position in the text, mirroring how a real delivery note lists a model
followed by its serials.
"""

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.services.extraction.rules import (
    _OCR_FIX_PAIRS,
    _loosen_for_ocr,
    _try_ocr_fixes,
    _unanchored,
)

_QUANTITY_WINDOW = 40
_QUANTITY_KEYWORDS = ("QTA", "QTÀ", "QUANTITA", "QUANTITÀ", "PZ", "PEZZI", "COLLI")
_QUANTITY_PATTERN = re.compile(r"\b(\d{1,4})\b")

_CHAR_CONFUSIONS: dict[str, set[str]] = {}
for _wrong, _right in _OCR_FIX_PAIRS:
    _CHAR_CONFUSIONS.setdefault(_wrong, set()).add(_right)
    _CHAR_CONFUSIONS.setdefault(_right, set()).add(_wrong)


def _ocr_tolerant_pattern(literal: str) -> str:
    """Builds a regex matching `literal` with any single character swapped
    for one it is commonly confused with by OCR (§7.2 stage 3). Used only to
    *locate* a known catalog part number in noisy text — the matched span is
    never returned as-is, the already-known catalog item is, so this cannot
    invent a part number that isn't in the catalog.
    """
    parts = []
    for ch in literal:
        alternatives = _CHAR_CONFUSIONS.get(ch)
        if alternatives:
            char_class = "".join(re.escape(c) for c in sorted({ch, *alternatives}))
            parts.append(f"[{char_class}]")
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


@dataclass
class CatalogItemRef:
    id: uuid.UUID
    part_number: str
    name: str
    vendor_code: str
    is_serialized: bool
    serial_pattern: str | None


@dataclass
class SerialOccurrence:
    position: int
    value: str
    catalog_item_id: uuid.UUID


@dataclass
class PartNumberOccurrence:
    position: int
    item: CatalogItemRef


@dataclass
class DocumentLine:
    catalog_item: CatalogItemRef
    quantity: Decimal | None
    serials: list[str]


def _find_serial_occurrences(
    upper_text: str, serialized_items: list[CatalogItemRef]
) -> list[SerialOccurrence]:
    occurrences: list[SerialOccurrence] = []
    seen_spans: set[tuple[int, int]] = set()
    for item in serialized_items:
        if not item.serial_pattern:
            continue
        strict_pattern = _unanchored(item.serial_pattern)
        for match in re.finditer(strict_pattern, upper_text):
            span = (match.start(), match.end())
            if span in seen_spans:
                continue
            seen_spans.add(span)
            occurrences.append(
                SerialOccurrence(
                    position=match.start(), value=match.group(0), catalog_item_id=item.id
                )
            )
        loose_pattern = _unanchored(_loosen_for_ocr(item.serial_pattern))
        for match in re.finditer(loose_pattern, upper_text):
            span = (match.start(), match.end())
            if span in seen_spans:
                continue
            fixed, corrected = _try_ocr_fixes(match.group(0), item.serial_pattern)
            if not corrected:
                continue
            seen_spans.add(span)
            occurrences.append(
                SerialOccurrence(position=match.start(), value=fixed, catalog_item_id=item.id)
            )
    occurrences.sort(key=lambda o: o.position)
    return occurrences


def _find_part_number_occurrences(
    upper_text: str, catalog_items: list[CatalogItemRef]
) -> list[PartNumberOccurrence]:
    occurrences: list[PartNumberOccurrence] = []
    for item in catalog_items:
        needle = item.part_number.upper()
        if len(needle) < 4:
            continue  # too short to search for reliably in a noisy OCR block
        seen_spans: set[tuple[int, int]] = set()
        start = 0
        while True:
            idx = upper_text.find(needle, start)
            if idx == -1:
                break
            seen_spans.add((idx, idx + len(needle)))
            occurrences.append(PartNumberOccurrence(position=idx, item=item))
            start = idx + len(needle)

        tolerant_pattern = _ocr_tolerant_pattern(needle)
        for match in re.finditer(tolerant_pattern, upper_text):
            span = (match.start(), match.end())
            if span in seen_spans or match.group(0) == needle:
                continue
            seen_spans.add(span)
            occurrences.append(PartNumberOccurrence(position=match.start(), item=item))
    occurrences.sort(key=lambda o: o.position)
    return occurrences


def _find_nearby_quantity(upper_text: str, position: int, part_number_len: int) -> Decimal | None:
    """Quantità dichiarata accanto a un codice articolo, o `None`.

    Solo un numero introdotto da una parola chiave ("QTA", "PZ", …) vale come
    quantità. Non esiste un ripiego del tipo "prendi il primo numero lì
    attorno": ce n'era uno, e su una riga reale leggeva `9200` da
    *"CATALYST 9200 4 X 10G"*, cioè il nome del prodotto. Una quantità
    sbagliata di due ordini di grandezza è molto peggio di una quantità
    mancante: quella mancante la vede l'operatore e la scrive, quella
    sbagliata la conferma senza guardare.
    """
    window_start = max(0, position - _QUANTITY_WINDOW)
    window_end = min(len(upper_text), position + part_number_len + _QUANTITY_WINDOW)
    window = upper_text[window_start:window_end]
    for keyword in _QUANTITY_KEYWORDS:
        keyword_pos = window.find(keyword)
        if keyword_pos == -1:
            continue
        after_keyword = window[keyword_pos + len(keyword) : keyword_pos + len(keyword) + 10]
        match = _QUANTITY_PATTERN.search(after_keyword)
        if match:
            return Decimal(match.group(1))
    return None


def extract_document_lines(
    raw_ocr_text: str, catalog_items: list[CatalogItemRef]
) -> tuple[list[DocumentLine], list[str]]:
    """Returns (grouped lines, serials that could not be matched to any line).

    Every returned serial is a literal (or single-OCR-fix-corrected, flagged
    as such by construction of `_find_serial_occurrences`) substring of
    `raw_ocr_text` — nothing here is generated.
    """
    upper_text = raw_ocr_text.upper()
    serialized_items = [item for item in catalog_items if item.is_serialized]

    part_number_hits = _find_part_number_occurrences(upper_text, catalog_items)
    serial_hits = _find_serial_occurrences(upper_text, serialized_items)

    if not part_number_hits:
        return [], [s.value for s in serial_hits]

    lines: list[DocumentLine] = []
    assigned_positions: set[int] = set()

    for index, hit in enumerate(part_number_hits):
        block_start = hit.position
        block_end = (
            part_number_hits[index + 1].position
            if index + 1 < len(part_number_hits)
            else len(upper_text)
        )
        block_serials = [
            s
            for s in serial_hits
            if block_start <= s.position < block_end and s.position not in assigned_positions
        ]
        for s in block_serials:
            assigned_positions.add(s.position)

        if hit.item.is_serialized:
            quantity = Decimal(len(block_serials)) if block_serials else None
        else:
            quantity = _find_nearby_quantity(upper_text, hit.position, len(hit.item.part_number))

        lines.append(
            DocumentLine(
                catalog_item=hit.item,
                quantity=quantity,
                serials=[s.value for s in block_serials],
            )
        )

    unassigned = [s.value for s in serial_hits if s.position not in assigned_positions]
    return lines, unassigned
