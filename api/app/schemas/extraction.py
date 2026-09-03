import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from app.models.enums import TemplateDocType
from app.schemas.common import OrmModel


class ExtractionTemplateCreate(BaseModel):
    name: str
    vendor_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    doc_type: TemplateDocType
    field_specs: dict[str, Any]
    llm_prompt: str | None = None
    priority: int = 100


class ExtractionTemplateUpdate(BaseModel):
    name: str | None = None
    vendor_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    doc_type: TemplateDocType | None = None
    field_specs: dict[str, Any] | None = None
    llm_prompt: str | None = None
    priority: int | None = None
    is_active: bool | None = None


class ExtractionTemplateResponse(OrmModel):
    id: uuid.UUID
    name: str
    vendor_id: uuid.UUID | None
    category_id: uuid.UUID | None
    doc_type: TemplateDocType
    field_specs: dict[str, Any]
    llm_prompt: str | None
    priority: int
    is_active: bool
    version: int
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ExtractedFieldResponse(BaseModel):
    field: str
    value: str
    confidence: str
    source: str
    corrected: bool


class MatchedCatalogItem(BaseModel):
    id: uuid.UUID
    part_number: str
    name: str
    vendor_code: str


class ExtractionResponse(BaseModel):
    # L'identificativo della riga in `extraction_runs`. Torna al chiamante per
    # una ragione sola: poter dire, dopo, se questa proposta è stata usata.
    # Senza, l'unico numero che direbbe se il modello serve a qualcosa non si
    # può registrare — ed è esattamente com'è stato finora.
    run_id: uuid.UUID | None = None
    fields: dict[str, ExtractedFieldResponse]
    conflicts: dict[str, list[ExtractedFieldResponse]]
    raw_barcodes: list[str]
    raw_ocr_text: str
    engine: str
    template_id: str | None
    template_name: str | None
    duration_ms: int
    matched_catalog_item: MatchedCatalogItem | None = None


class DocumentLineResponse(BaseModel):
    catalog_item: MatchedCatalogItem
    is_serialized: bool
    quantity: Decimal | None
    serials: list[str]


class DocumentExtractionResponse(BaseModel):
    """Whole-delivery-note reading: header fields (same as ExtractionResponse)
    plus proposed lines with their serials. Nothing here is auto-saved — the
    operator reviews and edits every line/serial before it becomes a real
    delivery note line or unit, same principle as single-field extraction.

    `analysis_job_id` is the structural reading by the model, which runs in the
    background: on a machine without a GPU it takes minutes, so it must never
    hold up this response. Poll it at `/extract/delivery-note/analysis/{id}`.
    """

    run_id: uuid.UUID | None = None
    fields: dict[str, ExtractedFieldResponse]
    lines: list[DocumentLineResponse]
    unassigned_serials: list[str]
    raw_ocr_text: str
    engine: str
    duration_ms: int
    analysis_job_id: str | None = None


class ProposedLineResponse(BaseModel):
    """Una riga come l'ha ricostruita il modello, già verificata contro il testo
    OCR: ogni seriale qui dentro è comparso alla lettera nel documento."""

    position: str
    description: str
    supplier_code: str | None
    part_number: str | None
    quantity: Decimal | None
    quantity_ordered: Decimal | None
    catalog_item: MatchedCatalogItem | None
    is_serialized: bool | None
    serials: list[str]
    secondary_serials: list[str]
    warnings: list[str]


class DocumentAnalysisResponse(BaseModel):
    status: Literal["running", "done", "failed"]
    lines: list[ProposedLineResponse] = []
    non_goods: list[str] = []
    unassigned_serials: list[str] = []
    model: str = ""
    duration_ms: int = 0
    error: str | None = None


class EsitoLetturaRequest(BaseModel):
    """L'operatore ha usato la proposta, oppure l'ha lasciata lì."""

    accepted: bool
