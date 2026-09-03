import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin
from app.models.enums import ItemCondition, item_condition_enum


class DeliveryNote(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "delivery_notes"
    __table_args__ = (
        UniqueConstraint("supplier_id", "number", name="uq_ddt_supplier_number"),
    )

    number: Mapped[str] = mapped_column(String, nullable=False)
    note_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    po_number: Mapped[str | None] = mapped_column(String)
    carrier: Mapped[str | None] = mapped_column(String)
    tracking_number: Mapped[str | None] = mapped_column(String)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    received_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    supplier: Mapped["Supplier"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    lines: Mapped[list["DeliveryNoteLine"]] = relationship(back_populates="delivery_note")


class DeliveryNoteLine(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "delivery_note_lines"
    __table_args__ = (UniqueConstraint("delivery_note_id", "line_number", name="uq_ddt_line"),)

    delivery_note_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("delivery_notes.id", ondelete="RESTRICT"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("catalog_items.id", ondelete="RESTRICT"), nullable=False
    )
    qty_expected: Mapped[float] = mapped_column(
        Numeric(12, 2), CheckConstraint("qty_expected > 0"), nullable=False
    )
    qty_received: Mapped[float] = mapped_column(
        Numeric(12, 2), CheckConstraint("qty_received >= 0"), nullable=False, default=0
    )
    condition: Mapped[ItemCondition] = mapped_column(
        item_condition_enum, nullable=False, default=ItemCondition.new
    )
    notes: Mapped[str | None] = mapped_column(Text)

    delivery_note: Mapped[DeliveryNote] = relationship(back_populates="lines")
    catalog_item: Mapped["CatalogItem"] = relationship()  # type: ignore[name-defined]  # noqa: F821
