import os
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..deps import get_session
from ..rbac import require_role
from ..schemas import (
    CountSessionCreate,
    CountScan,
    CountFinalizeOut,
    OutboundSessionCreate,
    OutboundScan,
    AdjustmentIn,
)
from ..barcode_resolver import resolve_barcode
from ..stock_utils import add_stock, sub_stock


router = APIRouter(tags=["scan"], prefix="")


async def _ensure_scan_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS count_session (
              id UUID PRIMARY KEY,
              warehouse_code VARCHAR(32) NOT NULL,
              status VARCHAR(16) NOT NULL DEFAULT 'open',
              note TEXT,
              user_id VARCHAR(64) NOT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT now(),
              closed_at TIMESTAMP
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS count_entry (
              id BIGSERIAL PRIMARY KEY,
              session_id UUID NOT NULL REFERENCES count_session(id) ON DELETE CASCADE,
              item_code VARCHAR(64) NOT NULL,
              batch VARCHAR(64),
              serial VARCHAR(64),
              qty NUMERIC(18,3) NOT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT now()
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS outbound_session (
              id UUID PRIMARY KEY,
              type VARCHAR(16) NOT NULL,
              warehouse_from VARCHAR(32) NOT NULL,
              warehouse_to VARCHAR(32),
              status VARCHAR(16) NOT NULL DEFAULT 'open',
              note TEXT,
              user_id VARCHAR(64) NOT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT now(),
              confirmed_at TIMESTAMP
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS outbound_entry (
              id BIGSERIAL PRIMARY KEY,
              session_id UUID NOT NULL REFERENCES outbound_session(id) ON DELETE CASCADE,
              item_code VARCHAR(64) NOT NULL,
              qty NUMERIC(18,3) NOT NULL,
              batch VARCHAR(64),
              serial VARCHAR(64),
              created_at TIMESTAMP NOT NULL DEFAULT now()
            )
            """
        )
    )


@router.post("/count/sessions")
async def create_count_session(
    payload: CountSessionCreate, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)
):
    require_role(user, "operator")
    await _ensure_scan_tables(session)
    sid = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO count_session(id, warehouse_code, note, user_id)
            VALUES (:id, :wh, :note, :uid)
            """
        ),
        {"id": sid, "wh": payload.warehouse_code, "note": payload.note, "uid": str(user.id)},
    )
    await session.commit()
    return {"id": sid}


@router.post("/count/sessions/{sid}/scan")
async def scan_count(sid: str, payload: CountScan, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    require_role(user, "operator")
    await _ensure_scan_tables(session)
    rs = await session.execute(text("SELECT status FROM count_session WHERE id=:id"), {"id": sid})
    row = rs.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Sesión no existe")
    if row[0] != "open":
        raise HTTPException(status_code=400, detail="Sesión cerrada")
    item_code, _ = resolve_barcode(payload.barcode)
    await session.execute(
        text(
            """
            INSERT INTO count_entry(session_id, item_code, batch, serial, qty)
            VALUES (:sid, :ic, :b, :s, :q)
            """
        ),
        {"sid": sid, "ic": item_code, "b": payload.batch, "s": payload.serial, "q": float(payload.qty)},
    )
    await session.commit()
    return {"ok": True}


@router.post("/count/sessions/{sid}/finalize")
async def finalize_count(
    sid: str, payload: CountFinalizeOut, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)
):
    require_role(user, "operator")
    await _ensure_scan_tables(session)
    rs = await session.execute(
        text("SELECT status, warehouse_code FROM count_session WHERE id=:id"), {"id": sid}
    )
    sess = rs.mappings().first()
    if sess is None:
        raise HTTPException(status_code=404, detail="Sesión no existe")
    if sess["status"] != "open":
        raise HTTPException(status_code=400, detail="Sesión ya cerrada")
    wh = sess["warehouse_code"]
    scans_rs = await session.execute(
        text(
            """
            SELECT item_code, COALESCE(batch,'') AS batch, COALESCE(serial,'') AS serial, SUM(qty) AS counted
              FROM count_entry WHERE session_id=:sid
             GROUP BY item_code, COALESCE(batch,''), COALESCE(serial,'')
            """
        ),
        {"sid": sid},
    )
    scans = [dict(r._mapping) for r in scans_rs]
    sys_rs = await session.execute(
        text(
            """
            SELECT item_code, COALESCE(batch,'') AS batch, COALESCE(serial,'') AS serial, qty
              FROM inventory_balance WHERE warehouse_code=:wh
            """
        ),
        {"wh": wh},
    )
    sys_rows = [dict(r._mapping) for r in sys_rs]
    sys_map: dict[tuple[str, str, str], float] = {
        (r["item_code"], r["batch"], r["serial"]): float(r["qty"]) for r in sys_rows
    }
    diffs: list[dict] = []
    for r in scans:
        k = (r["item_code"], r["batch"], r["serial"])
        system_qty = sys_map.pop(k, 0.0)
        delta = float(r["counted"]) - float(system_qty)
        if abs(delta) > 1e-9:
            diffs.append(
                {
                    "item_code": r["item_code"],
                    "warehouse": wh,
                    "batch": (r["batch"] or None),
                    "serial": (r["serial"] or None),
                    "delta": delta,
                }
            )
    for (ic, b, s), system_qty in sys_map.items():
        if abs(system_qty) > 1e-9:
            diffs.append({"item_code": ic, "warehouse": wh, "batch": (b or None), "serial": (s or None), "delta": -float(system_qty)})
    await session.execute(text("UPDATE count_session SET status='closed', closed_at=now() WHERE id=:id"), {"id": sid})
    await session.commit()
    if payload.adjustments:
        return {"closed": True, "proposed_adjustments": diffs}
    return {"closed": True, "differences": len(diffs)}


@router.post("/inventory/adjustments")
async def apply_adjustments(
    adjs: list[AdjustmentIn], session: AsyncSession = Depends(get_session), user=Depends(get_current_user)
):
    require_role(user, "operator")
    try:
        for a in adjs:
            if float(a.delta) > 0:
                await add_stock(session, a.item_code, a.warehouse, float(a.delta), a.batch, a.serial)
            elif float(a.delta) < 0:
                await sub_stock(session, a.item_code, a.warehouse, abs(float(a.delta)), a.batch, a.serial, False)
            await session.execute(
                text(
                    """
                    INSERT INTO movement(id, type, item_code, item_name, qty, uom, warehouse_to, batch, serial, reference, note, user_id)
                    VALUES (:id, 'ADJUST', :ic, :ic, :q, 'EA', :wh, :b, :s, NULL, :note, :uid)
                    """
                ),
                {
                    "id": str(uuid4()),
                    "ic": a.item_code,
                    "q": float(a.delta),
                    "wh": a.warehouse,
                    "b": a.batch,
                    "s": a.serial,
                    "note": a.note,
                    "uid": str(user.id),
                },
            )
        await session.commit()
        return {"ok": True, "count": len(adjs)}
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Error aplicando ajustes")


ENFORCE_STOCK = (os.getenv("ENFORCE_STOCK", "true").lower() in {"1", "true", "yes", "on"})


@router.post("/outbound/sessions")
async def create_outbound_session(
    payload: OutboundSessionCreate, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)
):
    require_role(user, "operator")
    await _ensure_scan_tables(session)
    if payload.type == "TRANSFER" and not payload.warehouse_to:
        raise HTTPException(status_code=400, detail="warehouse_to requerido en TRANSFER")
    sid = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO outbound_session(id, type, warehouse_from, warehouse_to, note, user_id)
            VALUES (:id, :t, :wf, :wt, :note, :uid)
            """
        ),
        {
            "id": sid,
            "t": payload.type,
            "wf": payload.warehouse_from,
            "wt": payload.warehouse_to,
            "note": payload.note,
            "uid": str(user.id),
        },
    )
    await session.commit()
    return {"id": sid}


@router.post("/outbound/sessions/{sid}/scan")
async def scan_outbound(sid: str, payload: OutboundScan, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    require_role(user, "operator")
    await _ensure_scan_tables(session)
    rs = await session.execute(text("SELECT status FROM outbound_session WHERE id=:id"), {"id": sid})
    row = rs.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Sesión no existe")
    if row[0] != "open":
        raise HTTPException(status_code=400, detail="Sesión cerrada")
    item_code, _ = resolve_barcode(payload.barcode)
    await session.execute(
        text(
            """
            INSERT INTO outbound_entry(session_id, item_code, qty, batch, serial)
            VALUES (:sid, :ic, :q, :b, :s)
            """
        ),
        {"sid": sid, "ic": item_code, "q": float(payload.qty), "b": payload.batch, "s": payload.serial},
    )
    await session.commit()
    return {"ok": True}


@router.post("/outbound/sessions/{sid}/confirm")
async def confirm_outbound(sid: str, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    require_role(user, "operator")
    await _ensure_scan_tables(session)
    rs = await session.execute(
        text("SELECT type, warehouse_from, warehouse_to, status FROM outbound_session WHERE id=:id"), {"id": sid}
    )
    sess = rs.mappings().first()
    if sess is None:
        raise HTTPException(status_code=404, detail="Sesión no existe")
    if sess["status"] != "open":
        raise HTTPException(status_code=400, detail="Sesión ya cerrada")
    rows_rs = await session.execute(
        text(
            """
            SELECT item_code, COALESCE(batch,'') AS batch, COALESCE(serial,'') AS serial, SUM(qty) qty
              FROM outbound_entry WHERE session_id=:sid
             GROUP BY item_code, COALESCE(batch,''), COALESCE(serial,'')
            """
        ),
        {"sid": sid},
    )
    rows = [dict(r._mapping) for r in rows_rs]
    try:
        for r in rows:
            b = r["batch"] or None
            s = r["serial"] or None
            await sub_stock(session, r["item_code"], sess["warehouse_from"], float(r["qty"]), b, s, ENFORCE_STOCK)
            await session.execute(
                text(
                    """
                    INSERT INTO movement(id, type, item_code, item_name, qty, uom, warehouse_from, warehouse_to, batch, serial, user_id)
                    VALUES (:id, :t, :ic, :ic, :q, 'EA', :wf, :wt, :b, :s, :uid)
                    """
                ),
                {
                    "id": str(uuid4()),
                    "t": ("OUTBOUND" if sess["type"] == "OUTBOUND" else "TRANSFER"),
                    "ic": r["item_code"],
                    "q": float(r["qty"]),
                    "wf": sess["warehouse_from"],
                    "wt": sess.get("warehouse_to"),
                    "b": b,
                    "s": s,
                    "uid": str(user.id),
                },
            )
            if sess["type"] == "TRANSFER":
                await add_stock(session, r["item_code"], sess["warehouse_to"], float(r["qty"]), b, s)
        await session.execute(text("UPDATE outbound_session SET status='confirmed', confirmed_at=now() WHERE id=:id"), {"id": sid})
        await session.commit()
        return {"ok": True, "lines": len(rows)}
    except HTTPException:
        # rethrow
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Error confirmando sesión") from exc

