import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import CurrentUser, DbSession, require_role
from app.exceptions import NotFoundError, ValidationAppError
from app.models.catalog import CatalogItem, Vendor
from app.models.enums import UserRole
from app.models.extraction import ExtractionRun, ExtractionTemplate
from app.models.users import User
from app.schemas.extraction import (
    DocumentAnalysisResponse,
    DocumentExtractionResponse,
    DocumentLineResponse,
    EsitoLetturaRequest,
    ExtractedFieldResponse,
    ExtractionResponse,
    ExtractionTemplateCreate,
    ExtractionTemplateResponse,
    ExtractionTemplateUpdate,
    MatchedCatalogItem,
    ProposedLineResponse,
)
from app.services.audit import write_audit
from app.services.extraction import jobs
from app.services.extraction.document_ai import propose_document_lines
from app.services.extraction.document_lines import CatalogItemRef, extract_document_lines
from app.services.extraction.documents import ALLOWED_MIME_TYPES, to_pages
from app.services.extraction.pipeline import auto_detect_template, run_extraction
from app.services.extraction.schemas import ExtractionOutcome
from app.services.extraction.templates import (
    load_active_templates,
    load_template_by_id,
    template_spec_from_model,
    template_spec_from_override,
)

router = APIRouter(tags=["extraction"])
settings = get_settings()

# Il PDF e i formati multipagina passano da `documents.to_pages`, che li
# riduce tutti a un elenco di pagine PNG prima della pipeline.
_MAX_PAGES = 15

# I template che descrivono un documento a pagina intera, non un'etichetta.
_DOCUMENT_DOC_TYPES = {"delivery_note", "packing_list", "invoice"}


def _outcome_to_response(outcome: ExtractionOutcome) -> ExtractionResponse:
    return ExtractionResponse(
        fields={
            k: ExtractedFieldResponse(
                field=v.field,
                value=v.value,
                confidence=v.confidence.value,
                source=v.source,
                corrected=v.corrected,
            )
            for k, v in outcome.fields.items()
        },
        conflicts={
            k: [
                ExtractedFieldResponse(
                    field=c.field,
                    value=c.value,
                    confidence=c.confidence.value,
                    source=c.source,
                    corrected=c.corrected,
                )
                for c in candidates
            ]
            for k, candidates in outcome.conflicts.items()
        },
        raw_barcodes=outcome.raw_barcodes,
        raw_ocr_text=outcome.raw_ocr_text,
        engine=outcome.engine,
        template_id=outcome.template_id,
        template_name=outcome.template_name,
        duration_ms=outcome.duration_ms,
    )


_CATALOG_MATCH_SIMILARITY_THRESHOLD = 0.4


async def _match_catalog_item(
    db: AsyncSession, outcome: ExtractionOutcome
) -> MatchedCatalogItem | None:
    """Resolves an extracted part number against the real catalog (§7.3
    `match_against_catalog`), so the operator can have the model pre-selected
    in the "Modello" dropdown instead of retyping it. Exact match first
    (case-insensitive), then trigram similarity above a threshold — never a
    blind "closest row", which would silently pick the wrong model.
    """
    candidate = outcome.fields.get("part_number")
    if candidate is None or not candidate.value.strip():
        return None

    exact = await db.execute(
        select(CatalogItem, Vendor)
        .join(Vendor, Vendor.id == CatalogItem.vendor_id)
        .where(
            func.upper(CatalogItem.part_number) == candidate.value.strip().upper(),
            CatalogItem.is_active.is_(True),
        )
        .limit(1)
    )
    row = exact.first()
    if row is None:
        similarity_expr = func.similarity(CatalogItem.part_number, candidate.value)
        fuzzy = await db.execute(
            select(CatalogItem, Vendor)
            .join(Vendor, Vendor.id == CatalogItem.vendor_id)
            .where(
                CatalogItem.is_active.is_(True),
                similarity_expr > _CATALOG_MATCH_SIMILARITY_THRESHOLD,
            )
            .order_by(similarity_expr.desc())
            .limit(1)
        )
        row = fuzzy.first()

    if row is None:
        return None

    item, vendor = row
    return MatchedCatalogItem(
        id=item.id, part_number=item.part_number, name=item.name, vendor_code=vendor.code
    )


async def _read_and_validate_images(images: list[UploadFile]) -> tuple[list[bytes], int]:
    """Legge i file caricati e li riduce a un elenco di pagine.

    Un PDF di bolla arrivato per mail vale quanto una fotografia: dopo questa
    funzione la pipeline non sa più da quale formato si sia partiti.
    """
    if not settings.extract_enabled:
        raise ValidationAppError(
            "L'estrazione automatica è disattivata su questa installazione (EXTRACT_ENABLED=false)."
        )
    if len(images) > settings.max_images_per_request:
        raise ValidationAppError(f"Massimo {settings.max_images_per_request} file per richiesta.")

    pages: list[bytes] = []
    total_bytes = 0
    for upload in images:
        declared = (upload.content_type or "").split(";")[0].strip().lower()
        if declared and declared not in ALLOWED_MIME_TYPES:
            raise ValidationAppError(
                f"Formato non supportato: {declared}. "
                "Ammessi JPEG, PNG, WebP, TIFF, BMP, GIF e PDF."
            )
        content = await upload.read()
        if len(content) > settings.max_image_bytes:
            raise ValidationAppError("File troppo grande (limite 15 MB).")
        total_bytes += len(content)
        pages.extend(to_pages(content, declared))

    if not pages:
        raise ValidationAppError("Nessuna pagina leggibile nei file caricati.")
    if len(pages) > _MAX_PAGES:
        raise ValidationAppError(
            f"Il documento ha {len(pages)} pagine: il limite è {_MAX_PAGES} per richiesta."
        )
    return pages, total_bytes


@router.post("/extract", response_model=ExtractionResponse)
async def extract(
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
    images: list[UploadFile] = File(...),
    template_id: str | None = Form(default=None),
    hint_category: str | None = Form(default=None),
) -> Any:
    image_bytes_list, total_bytes = await _read_and_validate_images(images)

    start = time.monotonic()
    error: str | None = None
    template = None
    try:
        if template_id:
            template = await load_template_by_id(db, template_id)
        else:
            templates = await load_active_templates(db)
            template = await auto_detect_template(templates, image_bytes_list)

        outcome = await run_extraction(image_bytes_list, template)
    except Exception as exc:  # noqa: BLE001 — extraction failures must not 500 the request
        error = str(exc)
        outcome = None
    finally:
        # §7.5: images exist only in this local scope; nothing persisted, nothing logged.
        image_bytes_list = []

    duration_ms = int((time.monotonic() - start) * 1000)

    run = ExtractionRun(
        user_id=user.id,
        template_id=uuid.UUID(template.id) if outcome and template else None,
        image_count=len(images),
        image_bytes=total_bytes,
        engine=outcome.engine if outcome else "error",
        # Solo **quali** campi sono stati risolti, non il loro valore: §7.5
        # dice che in `extraction_runs` resta l'esito e mai il contenuto, e un
        # registro che conserva per novanta giorni i seriali e i codici letti
        # dai documenti di un cliente è esattamente il contenuto.
        fields_found={k: True for k in outcome.fields} if outcome else {},
        confidence={k: v.confidence.value for k, v in outcome.fields.items()} if outcome else {},
        duration_ms=duration_ms,
        error=error,
    )
    db.add(run)
    await db.flush()

    if error or outcome is None:
        raise ValidationAppError(f"Estrazione fallita: {error or 'errore sconosciuto'}")

    response = _outcome_to_response(outcome)
    response.run_id = run.id
    response.matched_catalog_item = await _match_catalog_item(db, outcome)
    return response


@router.post("/extract/delivery-note", response_model=DocumentExtractionResponse)
async def extract_delivery_note(
    db: DbSession,
    user: User = Depends(require_role(UserRole.operator)),
    images: list[UploadFile] = File(...),
    template_id: str | None = Form(default=None),
) -> Any:
    """Reads a whole delivery note photo: header fields (like `/extract`)
    plus proposed lines with their serials, deterministically grouped by
    position in the OCR text (see `services/extraction/document_lines.py`
    for why this is not LLM-generated). Nothing is written to the
    warehouse — the operator reviews everything before it becomes a real
    delivery note line or unit.
    """
    image_bytes_list, total_bytes = await _read_and_validate_images(images)

    start = time.monotonic()
    error: str | None = None
    template = None
    try:
        if template_id:
            template = await load_template_by_id(db, template_id)
        else:
            # Solo fra i template di bolla: provare anche quelli di etichetta
            # significa rileggere ogni pagina con l'OCR una volta per template,
            # e rischiare che ne vinca uno che con questo documento non
            # c'entra nulla.
            templates = [
                candidate
                for candidate in await load_active_templates(db)
                if candidate.doc_type in _DOCUMENT_DOC_TYPES
            ]
            template = await auto_detect_template(templates, image_bytes_list)
        outcome = await run_extraction(
            image_bytes_list, template, doc_type_override="delivery_note"
        )
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        outcome = None
    finally:
        image_bytes_list = []

    duration_ms = int((time.monotonic() - start) * 1000)

    run = ExtractionRun(
        user_id=user.id,
        template_id=uuid.UUID(template.id) if outcome and template else None,
        image_count=len(images),
        image_bytes=total_bytes,
        engine=outcome.engine if outcome else "error",
        # Solo **quali** campi sono stati risolti, non il loro valore: §7.5
        # dice che in `extraction_runs` resta l'esito e mai il contenuto, e un
        # registro che conserva per novanta giorni i seriali e i codici letti
        # dai documenti di un cliente è esattamente il contenuto.
        fields_found={k: True for k in outcome.fields} if outcome else {},
        confidence={k: v.confidence.value for k, v in outcome.fields.items()} if outcome else {},
        duration_ms=duration_ms,
        error=error,
    )
    db.add(run)
    await db.flush()

    if error or outcome is None:
        raise ValidationAppError(f"Estrazione fallita: {error or 'errore sconosciuto'}")

    catalog_rows = (
        await db.execute(
            select(CatalogItem, Vendor)
            .join(Vendor, Vendor.id == CatalogItem.vendor_id)
            .where(CatalogItem.is_active.is_(True))
        )
    ).all()
    catalog_refs = [
        CatalogItemRef(
            id=item.id,
            part_number=item.part_number,
            name=item.name,
            vendor_code=vendor.code,
            is_serialized=item.is_serialized,
            serial_pattern=item.serial_pattern,
        )
        for item, vendor in catalog_rows
    ]

    lines, unassigned = extract_document_lines(outcome.raw_ocr_text, catalog_refs)

    # La lettura strutturale col modello parte adesso e prosegue per conto suo.
    # Su una macchina con GPU finisce in pochi secondi, senza GPU in minuti: in
    # entrambi i casi l'operatore riceve subito quello che c'è qui sotto, che è
    # già utilizzabile, e la proposta del modello lo raggiunge quando è pronta.
    analysis_job_id: str | None = None
    if settings.extract_enabled and outcome.raw_ocr_text.strip():
        ocr_text = outcome.raw_ocr_text
        analysis_job_id = await jobs.submit(lambda: propose_document_lines(ocr_text, catalog_refs))

    return DocumentExtractionResponse(
        run_id=run.id,
        fields={
            k: ExtractedFieldResponse(
                field=v.field,
                value=v.value,
                confidence=v.confidence.value,
                source=v.source,
                corrected=v.corrected,
            )
            for k, v in outcome.fields.items()
        },
        lines=[
            DocumentLineResponse(
                catalog_item=MatchedCatalogItem(
                    id=line.catalog_item.id,
                    part_number=line.catalog_item.part_number,
                    name=line.catalog_item.name,
                    vendor_code=line.catalog_item.vendor_code,
                ),
                is_serialized=line.catalog_item.is_serialized,
                quantity=line.quantity,
                serials=line.serials,
            )
            for line in lines
        ],
        unassigned_serials=unassigned,
        raw_ocr_text=outcome.raw_ocr_text,
        engine=outcome.engine,
        duration_ms=duration_ms,
        analysis_job_id=analysis_job_id,
    )


@router.get("/extract/delivery-note/analysis/{job_id}", response_model=DocumentAnalysisResponse)
async def delivery_note_analysis(
    job_id: str,
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    """Esito della lettura strutturale avviata da `/extract/delivery-note`.

    Finché `status` è "running" non c'è nulla da mostrare e va richiesto ancora.
    Un fallimento non è un errore HTTP: l'operatore ha già il risultato
    deterministico sullo schermo e può lavorare lo stesso.
    """
    job = jobs.get(job_id)
    if job is None:
        raise NotFoundError(
            "Analisi non trovata: potrebbe essere scaduta o l'API è stata riavviata.",
            details={"job_id": job_id},
        )
    if job.status != "done" or job.result is None:
        return DocumentAnalysisResponse(status=job.status, error=job.error)

    proposal = job.result
    return DocumentAnalysisResponse(
        status="done",
        model=proposal.model,
        duration_ms=proposal.duration_ms,
        non_goods=proposal.non_goods,
        unassigned_serials=proposal.unassigned_serials,
        lines=[
            ProposedLineResponse(
                position=line.position,
                description=line.description,
                supplier_code=line.supplier_code,
                part_number=line.part_number,
                quantity=line.quantity,
                quantity_ordered=line.quantity_ordered,
                catalog_item=(
                    MatchedCatalogItem(
                        id=line.catalog_item.id,
                        part_number=line.catalog_item.part_number,
                        name=line.catalog_item.name,
                        vendor_code=line.catalog_item.vendor_code,
                    )
                    if line.catalog_item
                    else None
                ),
                is_serialized=(line.catalog_item.is_serialized if line.catalog_item else None),
                serials=line.serials,
                secondary_serials=line.secondary_serials,
                warnings=line.warnings,
            )
            for line in proposal.lines
        ],
    )


@router.post("/extract/runs/{run_id}/esito", status_code=204)
async def registra_esito(
    run_id: uuid.UUID,
    payload: EsitoLetturaRequest,
    db: DbSession,
    user: CurrentUser,
) -> None:
    """Segna se la proposta del modello è servita a qualcosa.

    È l'unico numero che permette di decidere, fra un mese e con i dati in
    mano, se questa parte del sistema vale il suo costo — un container in
    più, un ADR di licenza, un modello da scaricare e minuti di CPU per
    documento. La colonna `accepted` esisteva già nel modello e non l'ha mai
    scritta nessuno: letture registrate a decine, e zero informazioni su
    quante fossero state usate.

    Non è un giudizio sulla qualità della lettura: dice solo che l'operatore
    ha portato quella proposta nel modulo invece di ribattere tutto a mano.
    """
    run = await db.get(ExtractionRun, run_id)
    if run is None:
        raise NotFoundError("Lettura non trovata.", details={"id": str(run_id)})
    # Chi ha fatto la lettura è l'unico che può dire se gli è servita.
    if run.user_id != user.id:
        raise NotFoundError("Lettura non trovata.", details={"id": str(run_id)})
    run.accepted = payload.accepted
    await db.flush()


@router.get("/extraction-templates", response_model=list[ExtractionTemplateResponse])
async def list_templates(db: DbSession, user: CurrentUser) -> Any:
    result = await db.execute(select(ExtractionTemplate).order_by(ExtractionTemplate.priority))
    return result.scalars().all()


@router.post("/extraction-templates", response_model=ExtractionTemplateResponse, status_code=201)
async def create_template(
    payload: ExtractionTemplateCreate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    template = ExtractionTemplate(**payload.model_dump(), created_by=user.id)
    db.add(template)
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="extraction_template.create",
        entity_type="extraction_template",
        entity_id=str(template.id),
        details={"name": template.name},
    )
    return template


@router.patch("/extraction-templates/{template_id}", response_model=ExtractionTemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    payload: ExtractionTemplateUpdate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    template = await db.get(ExtractionTemplate, template_id)
    if template is None:
        raise NotFoundError("Template non trovato.", details={"id": str(template_id)})
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(template, key, value)
    template.version += 1
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="extraction_template.update",
        entity_type="extraction_template",
        entity_id=str(template.id),
        details={"changed_fields": changes},
    )
    return template


@router.post("/extraction-templates/{template_id}/test", response_model=ExtractionResponse)
async def test_template(
    template_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
    images: list[UploadFile] = File(...),
    field_specs: str | None = Form(default=None),
) -> Any:
    """Playground (§7.3): tries a template — optionally with unsaved edits —
    against real images without writing anything to the warehouse. `field_specs`,
    when provided, is the JSON-encoded `{"fields": [...], "llm_instructions": ...}`
    the admin is currently editing in the UI; it overrides the saved template
    for this trial only and is never persisted here (use PATCH to save it).
    """
    model = await db.get(ExtractionTemplate, template_id)
    if model is None:
        raise NotFoundError("Template non trovato.", details={"id": str(template_id)})

    if field_specs:
        try:
            override = json.loads(field_specs)
        except json.JSONDecodeError as exc:
            raise ValidationAppError(f"field_specs non è un JSON valido: {exc}") from exc
        template = template_spec_from_override(model, override)
    else:
        template = template_spec_from_model(model)

    image_bytes_list, _total_bytes = await _read_and_validate_images(images)
    outcome = await run_extraction(image_bytes_list, template)
    response = _outcome_to_response(outcome)
    response.matched_catalog_item = await _match_catalog_item(db, outcome)
    return response
