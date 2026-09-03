from dataclasses import dataclass, field
from enum import Enum


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


@dataclass
class FieldCandidate:
    field: str
    value: str
    confidence: Confidence
    source: str  # 'barcode' | 'ocr_keyword' | 'ocr_regex' | 'llm'
    corrected: bool = False


@dataclass
class FieldSpec:
    name: str
    target: str
    regex: str | None = None
    keywords: list[str] = field(default_factory=list)
    keyword_window: int = 40
    barcode_formats: list[str] = field(default_factory=list)
    match_against_catalog: bool = False
    ocr_fixes: bool = False
    required: bool = False


@dataclass
class TemplateSpec:
    id: str
    name: str
    doc_type: str
    fields: list[FieldSpec]
    llm_instructions: str | None = None
    priority: int = 100


@dataclass
class ExtractionOutcome:
    fields: dict[str, FieldCandidate]
    conflicts: dict[str, list[FieldCandidate]]
    raw_barcodes: list[str]
    raw_ocr_text: str
    engine: str
    template_id: str | None
    template_name: str | None
    duration_ms: int
