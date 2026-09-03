import io

import zxingcpp
from PIL import Image

from app.services.extraction.schemas import Confidence, FieldCandidate, FieldSpec


def decode_barcodes(image_bytes: bytes) -> list[tuple[str, str]]:
    """Returns a list of (format_name, payload) decoded from the image."""
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return []

    results = zxingcpp.read_barcodes(image)
    return [(r.format.name, r.text) for r in results if r.text]


def classify_barcode_payloads(
    payloads: list[tuple[str, str]], field_specs: list[FieldSpec]
) -> tuple[list[FieldCandidate], list[str]]:
    candidates: list[FieldCandidate] = []
    unclassified: list[str] = []

    for barcode_format, payload in payloads:
        text = payload.strip()
        matched_any = False

        meraki_serial = _extract_meraki_url_serial(text)
        if meraki_serial:
            candidates.append(
                FieldCandidate(
                    field="serial_number",
                    value=meraki_serial,
                    confidence=Confidence.high,
                    source="barcode",
                )
            )
            matched_any = True

        for spec in field_specs:
            if spec.barcode_formats and barcode_format not in spec.barcode_formats:
                continue
            if spec.regex:
                import re

                if re.match(spec.regex, text):
                    candidates.append(
                        FieldCandidate(
                            field=spec.name,
                            value=text,
                            confidence=Confidence.high,
                            source="barcode",
                        )
                    )
                    matched_any = True

        if not matched_any:
            unclassified.append(text)

    return candidates, unclassified


def _extract_meraki_url_serial(text: str) -> str | None:
    import re

    match = re.search(r"[Qq][0-9A-Za-z]{3}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}", text)
    return match.group(0).upper() if match else None
