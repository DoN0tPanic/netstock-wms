import time

from app.config import get_settings
from app.services.extraction.barcode import classify_barcode_payloads, decode_barcodes
from app.services.extraction.fusion import fuse_candidates
from app.services.extraction.llm import extract_via_llm
from app.services.extraction.ocr import run_ocr
from app.services.extraction.rules import extract_all_fields
from app.services.extraction.schemas import (
    Confidence,
    ExtractionOutcome,
    FieldCandidate,
    TemplateSpec,
)
from app.services.extraction.verify import is_verifiable

settings = get_settings()


async def run_extraction(
    images: list[bytes],
    template: TemplateSpec | None,
    field_specs_override: list | None = None,
    doc_type_override: str | None = None,
) -> ExtractionOutcome:
    """`doc_type_override` serve dove il tipo di documento è già noto per
    costruzione — l'endpoint della bolla sa di leggere una bolla. Senza,
    vinceva il doc_type del template auto-rilevato: bastava che il rilevamento
    scegliesse un template di etichetta perché al foglio A4 venisse applicato
    il preprocessing pensato per un'etichetta piccola, che lo rende illeggibile
    (vedi services/extraction/ocr.py).
    """
    start = time.monotonic()
    field_specs = (
        field_specs_override
        if field_specs_override is not None
        else (template.fields if template else [])
    )

    per_image_candidates: list[list[FieldCandidate]] = []
    all_raw_barcodes: list[str] = []
    all_ocr_text_parts: list[str] = []
    engine_used = "barcode"

    for image_bytes in images:
        image_candidates: list[FieldCandidate] = []

        # Stage 1: barcode/QR — always first, deterministic.
        payloads = decode_barcodes(image_bytes)
        barcode_candidates, unclassified = classify_barcode_payloads(payloads, field_specs)
        image_candidates.extend(barcode_candidates)
        all_raw_barcodes.extend(unclassified)

        resolved_fields = {c.field for c in barcode_candidates}
        remaining_specs = [s for s in field_specs if s.name not in resolved_fields]

        ocr_text = ""
        if remaining_specs:
            # Stage 2: OCR.
            doc_type = doc_type_override or (template.doc_type if template else "device_label")
            try:
                ocr_text = run_ocr(image_bytes, doc_type)
            except Exception:
                ocr_text = ""
            all_ocr_text_parts.append(ocr_text)

            # Stage 3: deterministic rules on OCR text.
            rule_candidates = extract_all_fields(ocr_text, remaining_specs)
            image_candidates.extend(rule_candidates)
            engine_used = "ocr+rules"

            resolved_fields |= {c.field for c in rule_candidates}
            still_missing = [s for s in remaining_specs if s.name not in resolved_fields]

            # Stage 4: LLM on OCR text, only for still-empty required/optional fields.
            if still_missing and settings.extract_enabled and ocr_text.strip():
                extra_instructions = template.llm_instructions if template else None
                llm_result = await extract_via_llm(ocr_text, still_missing, extra_instructions)
                if llm_result:
                    engine_used = "ocr+llm"
                    source_text = ocr_text + " " + " ".join(all_raw_barcodes)
                    for spec in still_missing:
                        value = llm_result.get(spec.name)
                        if not value:
                            continue
                        # Stage 5: anti-hallucination verification — mandatory.
                        if is_verifiable(value, source_text):
                            image_candidates.append(
                                FieldCandidate(
                                    field=spec.name,
                                    value=value,
                                    confidence=Confidence.medium,
                                    source="llm",
                                )
                            )

        per_image_candidates.append(image_candidates)

    # Stage 6: multi-image fusion.
    winners, conflicts = fuse_candidates(per_image_candidates)

    duration_ms = int((time.monotonic() - start) * 1000)

    return ExtractionOutcome(
        fields=winners,
        conflicts=conflicts,
        raw_barcodes=all_raw_barcodes,
        raw_ocr_text="\n---\n".join(all_ocr_text_parts),
        engine=engine_used,
        template_id=template.id if template else None,
        template_name=template.name if template else None,
        duration_ms=duration_ms,
    )


_CONFIDENCE_WEIGHT = {Confidence.high: 3, Confidence.medium: 2, Confidence.low: 1}
_SOLID_CONFIDENCE = {Confidence.high, Confidence.medium}


async def auto_detect_template(
    templates: list[TemplateSpec], images: list[bytes]
) -> TemplateSpec | None:
    """Tries every active template and keeps the one that actually resolves
    its own fields best (§7.3: "si prova ogni template attivo in ordine di
    priority e vince quello che risolve più campi required con confidenza
    più alta"). Runs the same barcode + OCR/rules stages the full pipeline
    uses (skipping the LLM stage, which only matters once a template is
    already chosen) — a barcode-only check previously fell back to an
    arbitrary template whenever an image had no barcode, which is the
    normal case for a plain paper document like a delivery note, and could
    silently pick a template with no fields in common with the document.
    """
    if not templates:
        return None
    if len(templates) == 1:
        # Non c'è niente da scegliere, e la scelta costa un giro di OCR per
        # pagina: su una bolla di due pagine raddoppiava l'attesa prima ancora
        # di cominciare a leggerla.
        return templates[0]

    # Barcode payloads don't depend on the template, and OCR text only
    # depends on (image, doc_type) — several templates commonly share a
    # doc_type (e.g. three device_label templates), so caching both avoids
    # re-running tesseract once per template.
    barcode_cache: dict[int, list] = {}
    ocr_cache: dict[tuple[int, str], str] = {}

    best: TemplateSpec | None = None
    best_score: tuple[int, int, int, int, int] | None = None

    for template in templates:
        required_names = {f.name for f in template.fields if f.required}
        resolved: dict[str, Confidence] = {}

        for image_index, image_bytes in enumerate(images):
            if image_index not in barcode_cache:
                barcode_cache[image_index] = decode_barcodes(image_bytes)
            barcode_candidates, _ = classify_barcode_payloads(
                barcode_cache[image_index], template.fields
            )
            for c in barcode_candidates:
                resolved[c.field] = Confidence.high

            remaining_specs = [s for s in template.fields if s.name not in resolved]
            if remaining_specs:
                ocr_key = (image_index, template.doc_type)
                if ocr_key not in ocr_cache:
                    try:
                        ocr_cache[ocr_key] = run_ocr(image_bytes, template.doc_type)
                    except Exception:
                        ocr_cache[ocr_key] = ""
                ocr_text = ocr_cache[ocr_key]
                for c in extract_all_fields(ocr_text, remaining_specs):
                    if (
                        c.field not in resolved
                        or _CONFIDENCE_WEIGHT[c.confidence] > _CONFIDENCE_WEIGHT[resolved[c.field]]
                    ):
                        resolved[c.field] = c.confidence

        required_solid = sum(
            1 for name in required_names if resolved.get(name) in _SOLID_CONFIDENCE
        )
        required_any = sum(1 for name in required_names if name in resolved)
        total_solid = sum(1 for conf in resolved.values() if conf in _SOLID_CONFIDENCE)
        confidence_sum = sum(_CONFIDENCE_WEIGHT[conf] for conf in resolved.values())

        score = (required_solid, required_any, total_solid, confidence_sum, template.priority)
        if best_score is None or score > best_score:
            best_score = score
            best = template

    return best
