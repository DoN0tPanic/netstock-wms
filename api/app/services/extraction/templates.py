from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extraction import ExtractionTemplate
from app.services.extraction.schemas import FieldSpec, TemplateSpec


def _field_specs_from_dict(raw: dict[str, Any]) -> list[FieldSpec]:
    return [
        FieldSpec(
            name=f["name"],
            target=f.get("target", f["name"]),
            regex=f.get("regex"),
            keywords=f.get("keywords", []),
            keyword_window=f.get("keyword_window", 40),
            barcode_formats=f.get("barcode_formats", []),
            match_against_catalog=f.get("match_against_catalog", False),
            ocr_fixes=f.get("ocr_fixes", False),
            required=f.get("required", False),
        )
        for f in raw.get("fields", [])
    ]


def template_spec_from_model(model: ExtractionTemplate) -> TemplateSpec:
    return TemplateSpec(
        id=str(model.id),
        name=model.name,
        doc_type=model.doc_type.value,
        fields=_field_specs_from_dict(model.field_specs),
        llm_instructions=model.field_specs.get("llm_instructions") or model.llm_prompt,
        priority=model.priority,
    )


def template_spec_from_override(
    model: ExtractionTemplate, field_specs_override: dict[str, Any]
) -> TemplateSpec:
    """Builds a TemplateSpec from unsaved edits for the admin playground
    (§7.3 "zero codice, zero deploy"): an admin needs to see extraction
    results against a candidate field_specs edit *before* deciding to save
    it, never persisting the trial run itself.
    """
    return TemplateSpec(
        id=str(model.id),
        name=model.name,
        doc_type=model.doc_type.value,
        fields=_field_specs_from_dict(field_specs_override),
        llm_instructions=field_specs_override.get("llm_instructions") or model.llm_prompt,
        priority=model.priority,
    )


async def load_active_templates(db: AsyncSession) -> list[TemplateSpec]:
    result = await db.execute(
        select(ExtractionTemplate)
        .where(ExtractionTemplate.is_active.is_(True))
        .order_by(ExtractionTemplate.priority.asc())
    )
    return [template_spec_from_model(m) for m in result.scalars().all()]


async def load_template_by_id(db: AsyncSession, template_id: str) -> TemplateSpec | None:
    result = await db.execute(
        select(ExtractionTemplate).where(ExtractionTemplate.id == template_id)
    )
    model = result.scalar_one_or_none()
    return template_spec_from_model(model) if model else None
