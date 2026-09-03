import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import MACADDR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin
from app.models.enums import ItemCondition, UnitStatus, item_condition_enum, unit_status_enum


class StockUnit(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "stock_units"
    __table_args__ = (
        UniqueConstraint("catalog_item_id", "serial_number", name="uq_unit_item_serial"),
    )

    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("catalog_items.id", ondelete="RESTRICT"), nullable=False
    )
    serial_number: Mapped[str] = mapped_column(String, nullable=False)
    mac_address: Mapped[str | None] = mapped_column(MACADDR)
    status: Mapped[UnitStatus] = mapped_column(
        unit_status_enum, nullable=False, default=UnitStatus.in_stock
    )
    condition: Mapped[ItemCondition] = mapped_column(
        item_condition_enum, nullable=False, default=ItemCondition.new
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("locations.id", ondelete="RESTRICT")
    )
    delivery_note_line_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("delivery_note_lines.id", ondelete="RESTRICT")
    )
    purchase_date: Mapped[date | None] = mapped_column(Date)
    warranty_end: Mapped[date | None] = mapped_column(Date)
    contract_ref: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)

    catalog_item: Mapped["CatalogItem"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    location: Mapped["Location | None"] = relationship()  # type: ignore[name-defined]  # noqa: F821
