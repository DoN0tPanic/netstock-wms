import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import ItemCondition, MovementType, item_condition_enum, movement_type_enum


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(
            "location_from_id IS NOT NULL OR location_to_id IS NOT NULL",
            name="ck_movement_has_direction",
        ),
        CheckConstraint(
            "location_from_id IS DISTINCT FROM location_to_id OR location_from_id IS NULL",
            name="ck_movement_not_self",
        ),
        CheckConstraint(
            "stock_unit_id IS NULL OR quantity = 1",
            name="ck_serialized_qty",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    type: Mapped[MovementType] = mapped_column(movement_type_enum, nullable=False)
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("catalog_items.id", ondelete="RESTRICT"), nullable=False
    )
    stock_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stock_units.id", ondelete="RESTRICT")
    )
    quantity: Mapped[float] = mapped_column(
        Numeric(12, 2), CheckConstraint("quantity > 0"), nullable=False
    )
    condition: Mapped[ItemCondition] = mapped_column(
        item_condition_enum, nullable=False, default=ItemCondition.new
    )
    location_from_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("locations.id", ondelete="RESTRICT")
    )
    location_to_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("locations.id", ondelete="RESTRICT")
    )
    delivery_note_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("delivery_notes.id", ondelete="RESTRICT")
    )
    reference: Mapped[str | None] = mapped_column(Text)
    assignee: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stock_movements.id", ondelete="RESTRICT")
    )
    performed_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    catalog_item: Mapped["CatalogItem"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    stock_unit: Mapped["StockUnit | None"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    location_from: Mapped["Location | None"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys=[location_from_id]
    )
    location_to: Mapped["Location | None"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys=[location_to_id]
    )
    performer: Mapped["User"] = relationship()  # type: ignore[name-defined]  # noqa: F821
