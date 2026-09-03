import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin
from app.models.enums import LocationType, location_type_enum


class Vendor(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "vendors"

    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Category(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "categories"

    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT")
    )


class Supplier(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    vat_number: Mapped[str | None] = mapped_column(String)
    contact_ref: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Location(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "locations"

    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[LocationType] = mapped_column(location_type_enum, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("locations.id", ondelete="RESTRICT")
    )
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CatalogItem(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "catalog_items"
    __table_args__ = (UniqueConstraint("vendor_id", "part_number", name="uq_catalog_vendor_pn"),)

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    part_number: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_serialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    uom: Mapped[str] = mapped_column(String, nullable=False, default="PZ")
    reorder_point: Mapped[int | None] = mapped_column(Integer)
    eol_date: Mapped[date | None] = mapped_column(Date)
    eos_date: Mapped[date | None] = mapped_column(Date)
    serial_pattern: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    vendor: Mapped[Vendor] = relationship()
    category: Mapped[Category] = relationship()
