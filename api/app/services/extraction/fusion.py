from app.services.extraction.schemas import Confidence, FieldCandidate

_CONFIDENCE_RANK = {Confidence.high: 2, Confidence.medium: 1, Confidence.low: 0}
_SOURCE_RANK = {"barcode": 3, "ocr_keyword": 2, "llm": 1, "ocr_regex": 0}


def fuse_candidates(
    per_image_candidates: list[list[FieldCandidate]],
) -> tuple[dict[str, FieldCandidate], dict[str, list[FieldCandidate]]]:
    """Merges candidates across images/stages for the same field (§7.2 stage 6).

    Highest confidence wins; ties broken by source (barcode > OCR rules >
    LLM) and then by earliest image. Same-confidence conflicting values are
    returned in `conflicts`, never resolved silently.
    """
    by_field: dict[str, list[tuple[int, FieldCandidate]]] = {}

    for image_index, candidates in enumerate(per_image_candidates):
        for candidate in candidates:
            by_field.setdefault(candidate.field, []).append((image_index, candidate))

    winners: dict[str, FieldCandidate] = {}
    conflicts: dict[str, list[FieldCandidate]] = {}

    for field, entries in by_field.items():
        entries.sort(
            key=lambda pair: (
                -_CONFIDENCE_RANK[pair[1].confidence],
                -_SOURCE_RANK.get(pair[1].source, 0),
                pair[0],
            )
        )
        top_confidence = entries[0][1].confidence
        top_entries = [e for e in entries if e[1].confidence == top_confidence]
        distinct_values = {e[1].value for e in top_entries}

        if len(distinct_values) > 1:
            conflicts[field] = [e[1] for e in top_entries]
        else:
            winners[field] = entries[0][1]

    return winners, conflicts
