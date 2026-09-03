import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin
from app.models.enums import TemplateDocType, template_doc_type_enum


class ExtractionTemplate(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "extraction_templates"

    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="RESTRICT")
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT")
    )
    doc_type: Mapped[TemplateDocType] = mapped_column(template_doc_type_enum, nullable=False)
    field_specs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    llm_prompt: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("extraction_templates.id", ondelete="SET NULL")
    )
    image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    image_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    engine: Mapped[str] = mapped_column(String, nullable=False)
    fields_found: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted: Mapped[bool | None] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
