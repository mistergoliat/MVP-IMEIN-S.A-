import datetime as dt
import uuid
from typing import Optional

from pydantic import BaseModel, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class ProductImportResult(BaseModel):
    imported: int


class ProbeResponse(BaseModel):
    available: bool
    path: str | None = None


class DocScanRequest(BaseModel):
    scan: str


class DocScanResponse(BaseModel):
    doc_type: str
    doc_number: str


class PrintProductRequest(BaseModel):
    item_code: str
    item_name: Optional[str] = None
    fecha_ingreso: dt.date | None = None
    copies: int = Field(ge=1, le=10, default=1)


class PrintJobResponse(BaseModel):
    id: uuid.UUID
    printer_name: str
    status: str
    copies: int
    payload_zpl: str
    attempts: int
    last_error: Optional[str]
    created_at: dt.datetime


class PrintAckRequest(BaseModel):
    status: str
    error: Optional[str] = None


class MoveCreateRequest(BaseModel):
    doc_type: str = Field(pattern="^(PO|SO|TR|RT)$")
    doc_number: str = Field(min_length=1, max_length=64)


class MoveLineInput(BaseModel):
    item_code: str
    qty: int = Field(gt=0)
    qty_confirmed: Optional[int] = Field(default=None, ge=0)
    location_from: str = Field(default="MAIN", max_length=64)
    location_to: str = Field(default="MAIN", max_length=64)


class MoveConfirmRequest(BaseModel):
    lines: list[MoveLineInput]


class MoveLineResponse(BaseModel):
    id: uuid.UUID
    item_code: str
    qty: int
    qty_confirmed: int
    location_from: str
    location_to: str


class MoveResponse(BaseModel):
    id: uuid.UUID
    doc_type: str
    doc_number: str
    status: str
    type: str
    created_at: dt.datetime
    updated_at: dt.datetime
    lines: list[MoveLineResponse] = Field(default_factory=list)


# Goods Receipt (entrada)
class GrLineInput(BaseModel):
    item_code: str
    item_name: str
    uom: str = Field(default="EA", max_length=16)
    qty: float = Field(gt=0)
    batch: Optional[str] = Field(default=None, max_length=64)
    serial: Optional[str] = Field(default=None, max_length=64)


class GrCreateRequest(BaseModel):
    warehouse_to: str = Field(max_length=32)
    reference: Optional[str] = Field(default=None, max_length=64)
    note: Optional[str] = None
    lines: list[GrLineInput]
    print_all: bool = False


class GrCreateResponse(BaseModel):
    gr_id: uuid.UUID
    lines_count: int
    printed: bool


class ReceiptPrintResponse(BaseModel):
    gr_id: uuid.UUID
    jobs: int


# Listing schemas
class GrHeaderResponse(BaseModel):
    id: uuid.UUID
    warehouse_to: str
    reference: str | None = None
    note: str | None = None
    user_id: str
    created_at: dt.datetime
    lines_count: int


class GrLineView(BaseModel):
    item_code: str
    item_name: str
    uom: str
    qty: float
    batch: str | None = None
    serial: str | None = None


class GrDetailResponse(BaseModel):
    header: GrHeaderResponse
    lines: list[GrLineView]


class MoveListItem(BaseModel):
    id: uuid.UUID
    doc_type: str
    doc_number: str
    status: str
    type: str
    created_at: dt.datetime
    updated_at: dt.datetime
    lines_count: int | None = None


class ProductListItem(BaseModel):
    item_code: str
    item_name: str
    uom: str
    active: bool


class ProductCreateUpdate(BaseModel):
    item_code: str
    item_name: str
    uom: str = "EA"
    requires_lot: bool = False
    requires_serial: bool = False
    active: bool = True

# ===== Block A (MVP): Strong validation schemas =====
from typing import Optional, List, Literal
from uuid import UUID


class ReceiptLine(BaseModel):
    item_code: str = Field(min_length=1)
    item_name: str = Field(min_length=1)
    uom: str = Field(default="EA", min_length=1)
    qty: float = Field(gt=0)
    batch: Optional[str] = None
    serial: Optional[str] = None


class ReceiptIn(BaseModel):
    warehouse_to: str = Field(min_length=1)
    reference: Optional[str] = None
    note: Optional[str] = None
    print_all: bool = False
    lines: List[ReceiptLine] = Field(min_length=1)


class MovementIn(BaseModel):
    type: Literal["OUTBOUND", "TRANSFER", "RETURN", "ADJUST"]
    item_code: str = Field(min_length=1)
    item_name: str = Field(min_length=1)
    uom: str = Field(default="EA", min_length=1)
    qty: float = Field(gt=0)
    warehouse_from: Optional[str] = None
    warehouse_to: Optional[str] = None
    batch: Optional[str] = None
    serial: Optional[str] = None
    reference: Optional[str] = None
    note: Optional[str] = None


class ReceiptOut(BaseModel):
    gr_id: UUID
    lines_count: int
    printed: bool

# ===== Block D: HID scanning & counting =====
class CountSessionCreate(BaseModel):
    warehouse_code: str = Field(min_length=1)
    note: str | None = None


class CountScan(BaseModel):
    barcode: str = Field(min_length=1)
    qty: float = Field(gt=0, default=1)
    batch: str | None = None
    serial: str | None = None


class CountFinalizeOut(BaseModel):
    adjustments: bool = False


class OutboundSessionCreate(BaseModel):
    type: str = Field(pattern=r"^(OUTBOUND|TRANSFER)$")
    warehouse_from: str = Field(min_length=1)
    warehouse_to: str | None = None
    note: str | None = None


class OutboundScan(BaseModel):
    barcode: str = Field(min_length=1)
    qty: float = Field(gt=0, default=1)
    batch: str | None = None
    serial: str | None = None


class AdjustmentIn(BaseModel):
    item_code: str
    warehouse: str
    delta: float
    batch: str | None = None
    serial: str | None = None
    note: str | None = None
