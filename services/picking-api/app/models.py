import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class Product(Base):
    __tablename__ = "products"

    item_code: Mapped[str] = mapped_column(Text, primary_key=True)
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    ABC: Mapped[str | None] = mapped_column("abc", Text, nullable=True)
    XYZ: Mapped[str | None] = mapped_column("xyz", Text, nullable=True)
    unit_cost: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    monthly_mean: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    monthly_std: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    annual_qty: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    ACV: Mapped[float | None] = mapped_column("acv", Numeric, nullable=True)
    z_level: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    SS: Mapped[int | None] = mapped_column("ss", Integer, nullable=True)
    ROP: Mapped[int | None] = mapped_column("rop", Integer, nullable=True)
    EOQ: Mapped[int | None] = mapped_column("eoq", Integer, nullable=True)
    SMIN: Mapped[int | None] = mapped_column("smin", Integer, nullable=True)
    SMAX: Mapped[int | None] = mapped_column("smax", Integer, nullable=True)
    OnHand: Mapped[int | None] = mapped_column("onhand", Integer, nullable=True)
    BelowROP: Mapped[bool | None] = mapped_column("belowrop", Boolean, nullable=True)
    uom: Mapped[str] = mapped_column(Text, nullable=False, default="UN")
    requires_lot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_serial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class Stock(Base):
    __tablename__ = "stock"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_code: Mapped[str] = mapped_column(ForeignKey("products.item_code"), nullable=False)
    lot: Mapped[str | None] = mapped_column(Text, nullable=True)
    serial: Mapped[str | None] = mapped_column(Text, nullable=True)
    expiry: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    location: Mapped[str] = mapped_column(Text, nullable=False, default="MAIN")
    qty: Mapped[int] = mapped_column(Integer, nullable=False)


class Move(Base):
    __tablename__ = "moves"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    doc_number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    lines: Mapped[list["MoveLine"]] = relationship("MoveLine", back_populates="move", cascade="all, delete-orphan")


class MoveLine(Base):
    __tablename__ = "move_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    move_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("moves.id", ondelete="CASCADE"), nullable=False)
    item_code: Mapped[str] = mapped_column(ForeignKey("products.item_code"), nullable=False)
    lot: Mapped[str | None] = mapped_column(Text, nullable=True)
    serial: Mapped[str | None] = mapped_column(Text, nullable=True)
    expiry: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    location_from: Mapped[str] = mapped_column(Text, nullable=False, default="MAIN")
    location_to: Mapped[str] = mapped_column(Text, nullable=False, default="MAIN")

    move: Mapped[Move] = relationship("Move", back_populates="lines")


class Audit(Base):
    __tablename__ = "audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class PrintJob(Base):
    __tablename__ = "print_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    printer_name: Mapped[str] = mapped_column(Text, nullable=False)
    payload_zpl: Mapped[str] = mapped_column(Text, nullable=False)
    copies: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
