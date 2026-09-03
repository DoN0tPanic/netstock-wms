import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin
from app.models.enums import ReservationStatus, reservation_status_enum


class Reservation(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "reservations"

    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("catalog_items.id", ondelete="RESTRICT"), nullable=False
    )
    stock_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stock_units.id", ondelete="RESTRICT")
    )
    quantity: Mapped[float] = mapped_column(
        Numeric(12, 2), CheckConstraint("quantity > 0"), nullable=False
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("locations.id", ondelete="RESTRICT")
    )
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        reservation_status_enum, nullable=False, default=ReservationStatus.open
    )
    expires_at: Mapped[date | None] = mapped_column(Date)
    fulfilled_movement_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stock_movements.id", ondelete="RESTRICT")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    catalog_item: Mapped["CatalogItem"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    stock_unit: Mapped["StockUnit | None"] = relationship()  # type: ignore[name-defined]  # noqa: F821
