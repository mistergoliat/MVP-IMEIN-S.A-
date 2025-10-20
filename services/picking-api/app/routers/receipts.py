import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas, zpl
from ..auth import get_current_user
from ..deps import get_session
from ..rbac import require_role


router = APIRouter(prefix="/inventory", tags=["inventory"])


async def _ensure_gr_tables(session: AsyncSession) -> None:
    # asyncpg no permite múltiples comandos en una sola sentencia preparada
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS gr_header (
              id UUID PRIMARY KEY,
              warehouse_to VARCHAR(32) NOT NULL,
              reference VARCHAR(64),
              note TEXT,
              user_id VARCHAR(64) NOT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT now()
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS gr_line (
              id UUID PRIMARY KEY,
              gr_id UUID NOT NULL REFERENCES gr_header(id) ON DELETE CASCADE,
              item_code VARCHAR(64) NOT NULL,
              item_name VARCHAR(255) NOT NULL,
              uom VARCHAR(16) NOT NULL DEFAULT 'EA',
              qty NUMERIC(18,3) NOT NULL,
              batch VARCHAR(64),
              serial VARCHAR(64)
            )
            """
        )
    )


@router.post("/receipts", response_model=schemas.GrCreateResponse)
async def create_receipt(
    payload: schemas.GrCreateRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> schemas.GrCreateResponse:
    require_role(user, "operator")
    await _ensure_gr_tables(session)
    if not payload.lines:
        raise HTTPException(status_code=400, detail="Debe incluir al menos una línea")
    for ln in payload.lines:
        if ln.qty <= 0:
            raise HTTPException(status_code=400, detail="Las cantidades deben ser positivas")

    gr_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO gr_header (id, warehouse_to, reference, note, user_id, created_at)
            VALUES (:id, :wh, :ref, :note, :uid, now())
            """
        ),
        {"id": gr_id, "wh": payload.warehouse_to, "ref": payload.reference, "note": payload.note, "uid": str(user.id)},
    )
    ins_line = text(
        """
        INSERT INTO gr_line (id, gr_id, item_code, item_name, uom, qty, batch, serial)
        VALUES (:id, :gr, :code, :name, :uom, :qty, :batch, :serial)
        """
    )
    count = 0
    for ln in payload.lines:
        await session.execute(
            ins_line,
            {
                "id": uuid.uuid4(),
                "gr": gr_id,
                "code": ln.item_code,
                "name": ln.item_name[:255],
                "uom": ln.uom,
                "qty": float(ln.qty),
                "batch": ln.batch,
                "serial": ln.serial,
            },
        )
        count += 1

    # Optional immediate printing
    printed = False
    if payload.print_all:
        jobs = await _enqueue_receipt_labels(session, gr_id)
        printed = jobs > 0

    await session.commit()
    return schemas.GrCreateResponse(gr_id=gr_id, lines_count=count, printed=printed)


async def _enqueue_receipt_labels(session: AsyncSession, gr_id: uuid.UUID) -> int:
    rows = await session.execute(
        text(
            """
            SELECT l.item_code, l.item_name, l.qty, l.uom, l.batch, l.serial, h.warehouse_to AS warehouse
              FROM gr_line l
              JOIN gr_header h ON h.id = l.gr_id
             WHERE l.gr_id = :gr
             ORDER BY l.item_code
            """
        ),
        {"gr": gr_id},
    )
    lines = [dict(r._mapping) for r in rows]
    if not lines:
        return 0
    # Build print jobs (one per line, copies = qty rounded up to int, max 50)
    jobs = 0
    for ln in lines:
        # Build per-line ZPL using extended receipt template
        zpl_payload = zpl.build_zpl_label(
            item_code=str(ln["item_code"]),
            item_name=str(ln["item_name"]),
            qty=float(ln.get("qty") or 1),
            uom=str(ln.get("uom") or "EA"),
            warehouse=str(ln.get("warehouse") or ""),
            batch=(ln.get("batch") if ln.get("batch") is not None else None),
            serial=(ln.get("serial") if ln.get("serial") is not None else None),
        )
        await session.execute(
            text(
                """
                INSERT INTO print_jobs (id, printer_name, payload_zpl, copies, status, attempts, created_at, updated_at)
                VALUES (gen_random_uuid(), :printer, :zpl, :copies, 'queued', 0, now(), now())
                """
            ),
            {"printer": "ZDesigner ZD888t", "zpl": zpl_payload, "copies": 1},
        )
        jobs += 1
    return jobs


@router.post("/labels/print/receipt/{gr_id}", response_model=schemas.ReceiptPrintResponse)
async def print_receipt_labels(
    gr_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> schemas.ReceiptPrintResponse:
    require_role(user, "operator")
    await _ensure_gr_tables(session)
    jobs = await _enqueue_receipt_labels(session, gr_id)
    await session.commit()
    return schemas.ReceiptPrintResponse(gr_id=gr_id, jobs=jobs)


@router.get("/receipts", response_model=list[schemas.GrHeaderResponse])
async def list_receipts(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    q: str | None = None,
    warehouse: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    require_role(user, "operator")
    await _ensure_gr_tables(session)
    filters: list[str] = []
    params: dict[str, object] = {"limit": limit, "offset": offset}
    if q:
        filters.append("(reference ILIKE :q OR note ILIKE :q)")
        params["q"] = f"%{q}%"
    if warehouse:
        filters.append("warehouse_to = :wh")
        params["wh"] = warehouse
    if date_from:
        filters.append("created_at >= :from")
        params["from"] = date_from
    if date_to:
        filters.append("created_at <= :to")
        params["to"] = date_to
    where = (" WHERE " + " AND ".join(filters)) if filters else ""
    sql = text(
        f"""
        SELECT h.id, h.warehouse_to, h.reference, h.note, h.user_id, h.created_at,
               COALESCE((SELECT COUNT(1) FROM gr_line l WHERE l.gr_id = h.id), 0) AS lines_count
        FROM gr_header h
        {where}
        ORDER BY h.created_at DESC
        LIMIT :limit OFFSET :offset
        """
    )
    rows = await session.execute(sql, params)
    items = [dict(r._mapping) for r in rows]
    # Pydantic will coerce types where possible
    return [schemas.GrHeaderResponse(**it) for it in items]


@router.get("/receipts/{gr_id}", response_model=schemas.GrDetailResponse)
async def get_receipt_detail(
    gr_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    require_role(user, "operator")
    await _ensure_gr_tables(session)
    hdr_q = text(
        """
        SELECT h.id, h.warehouse_to, h.reference, h.note, h.user_id, h.created_at,
               COALESCE((SELECT COUNT(1) FROM gr_line l WHERE l.gr_id = h.id), 0) AS lines_count
        FROM gr_header h WHERE h.id = :id
        """
    )
    row = await session.execute(hdr_q, {"id": gr_id})
    h = row.mappings().first()
    if not h:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    lines_q = text(
        """
        SELECT item_code, item_name, uom, qty, batch, serial
        FROM gr_line WHERE gr_id = :id ORDER BY item_code
        """
    )
    lrows = await session.execute(lines_q, {"id": gr_id})
    lines = [schemas.GrLineView(**dict(r._mapping)) for r in lrows]
    header = schemas.GrHeaderResponse(**dict(h))
    return schemas.GrDetailResponse(header=header, lines=lines)


@router.get("/receipts/export")
async def export_receipts_csv(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    q: str | None = None,
    warehouse: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Export CSV for receipts header with filters."""
    require_role(user, "operator")
    await _ensure_gr_tables(session)
    filters: list[str] = []
    params: dict[str, object] = {}
    if q:
        filters.append("(reference ILIKE :q OR note ILIKE :q)")
        params["q"] = f"%{q}%"
    if warehouse:
        filters.append("warehouse_to = :wh")
        params["wh"] = warehouse
    if date_from:
        filters.append("created_at >= :from")
        params["from"] = date_from
    if date_to:
        filters.append("created_at <= :to")
        params["to"] = date_to
    where = (" WHERE " + " AND ".join(filters)) if filters else ""
    sql = text(
        f"""
        SELECT h.id, h.warehouse_to, h.reference, h.note, h.user_id, h.created_at,
               COALESCE((SELECT COUNT(1) FROM gr_line l WHERE l.gr_id = h.id), 0) AS lines_count
        FROM gr_header h
        {where}
        ORDER BY h.created_at DESC
        """
    )
    rows = await session.execute(sql, params)
    import csv, io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "warehouse_to", "reference", "note", "user_id", "created_at", "lines_count"])
    for r in rows:
        m = r._mapping
        writer.writerow([m["id"], m["warehouse_to"], m["reference"], m["note"], m["user_id"], m["created_at"], m["lines_count"]])
    from fastapi import Response
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=receipts.csv"},
    )
