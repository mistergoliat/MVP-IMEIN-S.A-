import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import ReceiptIn, ReceiptOut, MovementIn
from ..deps import get_session
from ..auth import get_current_user
from ..rbac import require_role
from ..stock_utils import add_stock, sub_stock, _ensure_item
from .receipts import _enqueue_receipt_labels  # reuse existing label print logic


router = APIRouter()


ENFORCE_STOCK = (os.getenv("ENFORCE_STOCK", "true").lower() in {"1", "true", "yes", "on"})


async def _ensure_core_tables(session: AsyncSession) -> None:
    # Ensure minimal tables exist (for dev environments without migrations)
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS warehouse (
              id SERIAL PRIMARY KEY,
              code VARCHAR(32) UNIQUE NOT NULL,
              name VARCHAR(255) NOT NULL
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS item_master (
              id SERIAL PRIMARY KEY,
              item_code VARCHAR(64) UNIQUE NOT NULL,
              item_name VARCHAR(255) NOT NULL,
              uom VARCHAR(16) NOT NULL DEFAULT 'EA',
              tracking_mode VARCHAR(10) NOT NULL DEFAULT 'NONE',
              status VARCHAR(16) NOT NULL DEFAULT 'active'
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS inventory_balance (
              id BIGSERIAL PRIMARY KEY,
              item_code VARCHAR(64) NOT NULL REFERENCES item_master(item_code),
              warehouse_code VARCHAR(32) NOT NULL REFERENCES warehouse(code),
              batch VARCHAR(64),
              serial VARCHAR(64),
              qty NUMERIC(18,3) NOT NULL DEFAULT 0
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_balance
              ON inventory_balance(item_code, warehouse_code, COALESCE(batch,''), COALESCE(serial,''))
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS movement (
              id UUID PRIMARY KEY,
              type VARCHAR(16) NOT NULL,
              item_code VARCHAR(64) NOT NULL REFERENCES item_master(item_code),
              item_name VARCHAR(255) NOT NULL,
              qty NUMERIC(18,3) NOT NULL,
              uom VARCHAR(16) NOT NULL,
              warehouse_from VARCHAR(32),
              warehouse_to VARCHAR(32),
              batch VARCHAR(64),
              serial VARCHAR(64),
              reference VARCHAR(64),
              note TEXT,
              user_id VARCHAR(64) NOT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT now()
            )
            """
        )
    )


@router.post("/receipts", response_model=ReceiptOut)
async def create_receipt(
    payload: ReceiptIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> ReceiptOut:
    require_role(user, "operator")
    await _ensure_core_tables(session)
    try:
        gr_id = uuid.uuid4()
        await session.execute(
            text(
                """
                INSERT INTO gr_header(id, warehouse_to, reference, note, user_id)
                VALUES (:id, :wh, :ref, :note, :uid)
                """
            ),
            {"id": str(gr_id), "wh": payload.warehouse_to, "ref": payload.reference, "note": payload.note, "uid": str(user.id)},
        )

        ins_line = text(
            """
            INSERT INTO gr_line(id, gr_id, item_code, item_name, uom, qty, batch, serial)
            VALUES (:id, :gr, :ic, :in, :u, :q, :b, :s)
            """
        )

        for ln in payload.lines:
            await _ensure_item(session, ln.item_code, ln.item_name, ln.uom)
            await session.execute(
                ins_line,
                {
                    "id": str(uuid.uuid4()),
                    "gr": str(gr_id),
                    "ic": ln.item_code,
                    "in": ln.item_name,
                    "u": ln.uom,
                    "q": float(ln.qty),
                    "b": ln.batch,
                    "s": ln.serial,
                },
            )

            await session.execute(
                text(
                    """
                    INSERT INTO movement(id, type, item_code, item_name, qty, uom, warehouse_to, batch, serial, reference, note, user_id)
                    VALUES (:id, 'INBOUND', :ic, :in, :q, :u, :wh, :b, :s, :ref, :note, :uid)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "ic": ln.item_code,
                    "in": ln.item_name,
                    "q": float(ln.qty),
                    "u": ln.uom,
                    "wh": payload.warehouse_to,
                    "b": ln.batch,
                    "s": ln.serial,
                    "ref": payload.reference,
                    "note": payload.note,
                    "uid": str(user.id),
                },
            )

            await add_stock(session, ln.item_code, payload.warehouse_to, float(ln.qty), ln.batch, ln.serial)

        await session.commit()

        printed = False
        if payload.print_all:
            try:
                jobs = await _enqueue_receipt_labels(session, gr_id)
                printed = jobs > 0
                await session.commit()
            except Exception:
                # Non-fatal
                await session.rollback()
                printed = False

        return ReceiptOut(gr_id=gr_id, lines_count=len(payload.lines), printed=printed)
    except ValueError as ve:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Error interno creando la recepción")


@router.post("/inventory/movements")
async def create_movement(
    mv: MovementIn, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)
) -> dict[str, Any]:
    require_role(user, "operator")
    await _ensure_core_tables(session)
    try:
        await _ensure_item(session, mv.item_code, mv.item_name, mv.uom)
        mov_id = uuid.uuid4()

        if mv.type == "OUTBOUND":
            if not mv.warehouse_from:
                raise ValueError("warehouse_from requerido")
            await sub_stock(
                session, mv.item_code, mv.warehouse_from, float(mv.qty), mv.batch, mv.serial, ENFORCE_STOCK
            )
            await session.execute(
                text(
                    """
                    INSERT INTO movement(id, type, item_code, item_name, qty, uom, warehouse_from, batch, serial, reference, note, user_id)
                    VALUES (:id, 'OUTBOUND', :ic, :in, :q, :u, :wf, :b, :s, :ref, :note, :uid)
                    """
                ),
                {
                    "id": str(mov_id),
                    "ic": mv.item_code,
                    "in": mv.item_name,
                    "q": float(mv.qty),
                    "u": mv.uom,
                    "wf": mv.warehouse_from,
                    "b": mv.batch,
                    "s": mv.serial,
                    "ref": mv.reference,
                    "note": mv.note,
                    "uid": str(user.id),
                },
            )

        elif mv.type == "TRANSFER":
            if not mv.warehouse_from or not mv.warehouse_to:
                raise ValueError("warehouse_from y warehouse_to requeridos")
            await sub_stock(
                session, mv.item_code, mv.warehouse_from, float(mv.qty), mv.batch, mv.serial, ENFORCE_STOCK
            )
            await add_stock(session, mv.item_code, mv.warehouse_to, float(mv.qty), mv.batch, mv.serial)
            await session.execute(
                text(
                    """
                    INSERT INTO movement(id, type, item_code, item_name, qty, uom, warehouse_from, warehouse_to, batch, serial, reference, note, user_id)
                    VALUES (:id, 'TRANSFER', :ic, :in, :q, :u, :wf, :wt, :b, :s, :ref, :note, :uid)
                    """
                ),
                {
                    "id": str(mov_id),
                    "ic": mv.item_code,
                    "in": mv.item_name,
                    "q": float(mv.qty),
                    "u": mv.uom,
                    "wf": mv.warehouse_from,
                    "wt": mv.warehouse_to,
                    "b": mv.batch,
                    "s": mv.serial,
                    "ref": mv.reference,
                    "note": mv.note,
                    "uid": str(user.id),
                },
            )

        elif mv.type == "RETURN":
            if not mv.warehouse_to:
                raise ValueError("warehouse_to requerido")
            await add_stock(session, mv.item_code, mv.warehouse_to, float(mv.qty), mv.batch, mv.serial)
            await session.execute(
                text(
                    """
                    INSERT INTO movement(id, type, item_code, item_name, qty, uom, warehouse_to, batch, serial, reference, note, user_id)
                    VALUES (:id, 'RETURN', :ic, :in, :q, :u, :wt, :b, :s, :ref, :note, :uid)
                    """
                ),
                {
                    "id": str(mov_id),
                    "ic": mv.item_code,
                    "in": mv.item_name,
                    "q": float(mv.qty),
                    "u": mv.uom,
                    "wt": mv.warehouse_to,
                    "b": mv.batch,
                    "s": mv.serial,
                    "ref": mv.reference,
                    "note": mv.note,
                    "uid": str(user.id),
                },
            )

        elif mv.type == "ADJUST":
            if not mv.warehouse_to:
                raise ValueError("warehouse_to requerido en ADJUST")
            if float(mv.qty) >= 0:
                await add_stock(session, mv.item_code, mv.warehouse_to, float(mv.qty), mv.batch, mv.serial)
            else:
                await sub_stock(session, mv.item_code, mv.warehouse_to, abs(float(mv.qty)), mv.batch, mv.serial, False)
            await session.execute(
                text(
                    """
                    INSERT INTO movement(id, type, item_code, item_name, qty, uom, warehouse_to, batch, serial, reference, note, user_id)
                    VALUES (:id, 'ADJUST', :ic, :in, :q, :u, :wt, :b, :s, :ref, :note, :uid)
                    """
                ),
                {
                    "id": str(mov_id),
                    "ic": mv.item_code,
                    "in": mv.item_name,
                    "q": float(mv.qty),
                    "u": mv.uom,
                    "wt": mv.warehouse_to,
                    "b": mv.batch,
                    "s": mv.serial,
                    "ref": mv.reference,
                    "note": mv.note,
                    "uid": str(user.id),
                },
            )

        else:
            raise ValueError("Tipo de movimiento no soportado")

        await session.commit()
        return {"id": str(mov_id), "ok": True}
    except ValueError as ve:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Error interno creando el movimiento")


@router.get("/inventory/balances")
async def get_balances(
    item_code: str | None = None,
    warehouse: str | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    require_role(user, "operator")
    await _ensure_core_tables(session)
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if item_code:
        clauses.append("item_code = :i")
        params["i"] = item_code
    if warehouse:
        clauses.append("warehouse_code = :w")
        params["w"] = warehouse
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = await session.execute(
        text(
            f"""
            SELECT item_code, warehouse_code, batch, serial, qty
            FROM inventory_balance {where}
            ORDER BY item_code, warehouse_code
            """
        ),
        params,
    )
    return [dict(r._mapping) for r in rows]


@router.get("/inventory/warehouses")
async def list_warehouses(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    require_role(user, "operator")
    await _ensure_core_tables(session)
    # Seed required warehouses (idempotent)
    seeds: list[tuple[str, str]] = [
        ("BP", "Bodega Principal"),
        ("BR", "Bodega Recepción"),
        ("Z2", "Felipe Aguilar"),
        ("M10", "Cristian Gallegos"),
        ("M7", "Jorge Ibarra"),
        ("M3", "Freddy Marquez"),
        ("M12", "Jermain Orellana"),
        ("M6", "Esteban Rivas"),
        ("Z1", "Cristian Salinas"),
        ("M1", "Roberto Vasquez"),
        ("M2", "Juan Vera"),
        ("M4", "Juan Carlos Vera"),
    ]
    await session.execute(
        text(
            """
            INSERT INTO warehouse(code, name)
            VALUES (:c, :n)
            ON CONFLICT (code) DO NOTHING
            """
        ),
        [{"c": c, "n": n} for c, n in seeds],
    )
    await session.commit()
    rows = await session.execute(text("SELECT code, name FROM warehouse ORDER BY code"))
    return [dict(r._mapping) for r in rows]


@router.get("/inventory/movements")
async def get_movements(limit: int = 100, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    require_role(user, "operator")
    await _ensure_core_tables(session)
    rows = await session.execute(
        text(
            """
            SELECT id, type, item_code, item_name, qty, uom, warehouse_from, warehouse_to, batch, serial, reference, note, user_id, created_at
            FROM movement ORDER BY created_at DESC LIMIT :lim
            """
        ),
        {"lim": limit},
    )
    return [dict(r._mapping) for r in rows]
