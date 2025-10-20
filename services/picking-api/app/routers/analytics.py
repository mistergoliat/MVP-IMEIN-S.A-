from io import BytesIO, StringIO
from typing import Any
import unicodedata

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..deps import get_session
from ..rbac import require_role


router = APIRouter(prefix="/analytics/abcxyz", tags=["analytics"])


async def _table_exists(session: AsyncSession) -> bool:
    """Return True if abcxyz_results table exists (PostgreSQL)."""
    rs = await session.execute(text("SELECT to_regclass('public.abcxyz_results')"))
    return rs.scalar() is not None


async def _table_exists_name(session: AsyncSession, table: str) -> bool:
    rs = await session.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"})
    return rs.scalar() is not None


from datetime import date, datetime, timedelta


def _parse_period_to_range(period: str | None) -> tuple[date | None, date | None]:
    """Best-effort parse of period string to [date_from, date_to) ISO dates.

    Supports:
    - 'YYYY-MM-DD' (daily)
    - 'DD-MM-YYYY' (daily)
    - 'YYYY-MM' (monthly; covers full month)
    Returns ISO date strings (YYYY-MM-DD) or (None, None) if not parseable.
    """
    if not period:
        return None, None
    try:
        d = datetime.strptime(period, "%Y-%m-%d").date()
        return d, (d + timedelta(days=1))
    except Exception:
        pass
    try:
        d = datetime.strptime(period, "%d-%m-%Y").date()
        return d, (d + timedelta(days=1))
    except Exception:
        pass
    try:
        d = datetime.strptime(period, "%Y-%m").date().replace(day=1)
        # next month first day
        if d.month == 12:
            d2 = d.replace(year=d.year + 1, month=1, day=1)
        else:
            d2 = d.replace(month=d.month + 1, day=1)
        return d, d2
    except Exception:
        return None, None


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    period: str = Form(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    if not period:
        raise HTTPException(status_code=400, detail="period requerido")
    # Require supervisor to ingest
    require_role(user, "supervisor")

    name = (file.filename or "").lower()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacio")

    try:
        if name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(BytesIO(content))
        else:
            # try CSV as utf-8; fallback to latin-1
            try:
                df = pd.read_csv(StringIO(content.decode("utf-8")))
            except UnicodeDecodeError:
                df = pd.read_csv(StringIO(content.decode("latin-1")))
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=f"No se pudo leer el archivo: {exc}")

    df.columns = [str(c).strip().lower() for c in df.columns]

    # Build a normalized lookup to tolerate accents/spaces/hyphens/underscores
    def _strip_accents(s: str) -> str:
        return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))

    def _norm(s: str) -> str:
        s2 = _strip_accents(s.lower().strip())
        for ch in (" ", "-", "_"):
            s2 = s2.replace(ch, "")
        return s2

    original_cols = list(df.columns)
    norm_map: dict[str, str] = {}
    for c in original_cols:
        n = _norm(c)
        if n not in norm_map:
            norm_map[n] = c

    # Canonical columns and synonyms (normalized)
    synonyms = {
        "item_code": ["itemcode", "code", "codigo", "codigoproducto", "sku", "productcode", "item", "articulo"],
        "abc": ["abc"],
        "xyz": ["xyz"],
        "class": ["class", "clase", "categoria", "classification", "clasificacion", "cls"],
        "policy": ["policy", "politica", "politicas", "policyname", "policies"],
        "stock": ["stock", "onhand", "existencia", "existencias"],
        "turnover": ["turnover", "rotacion", "rotation"],
        "revenue": ["revenue", "ventas", "ingresos"],
        "min_qty": ["minqty", "min", "smin", "minimo", "minima"],
        "max_qty": ["maxqty", "max", "smax", "maximo", "maxima"],
        "item_name": ["itemname", "nombre", "descripcion", "name", "productname"],
    }

    rename_map: dict[str, str] = {}
    for canonical, alts in synonyms.items():
        if canonical in df.columns:
            continue
        found_src = next((norm_map[a] for a in alts if a in norm_map), None)
        if found_src:
            rename_map[found_src] = canonical
    if rename_map:
        df = df.rename(columns=rename_map)
    # Minimal required: item_code, abc, xyz. We will derive class/policy if missing.
    required = {"item_code", "abc", "xyz"}
    if not required.issubset(df.columns):
        missing = ", ".join(sorted(required - set(df.columns)))
        raise HTTPException(status_code=400, detail=f"Columnas faltantes: {missing}")

    # Default policy mapping by composite class (AX, AY, ...)
    POLICY_DEFAULTS = {
        "AX": "Revisión continua · SL alto · ROP ajustado",
        "AY": "Revisión semanal · Buffer moderado",
        "AZ": "Planificación cuidadosa · Lotes pequeños",
        "BX": "Revisión continua · SL medio",
        "BY": "Revisión quincenal",
        "BZ": "Revisión por pedido · bajo stock",
        "CX": "Revisión mensual · stock mínimo",
        "CY": "Revisión mensual",
        "CZ": "Bajo volumen · bajo stock",
    }

    # Ensure destination table exists (idempotent)
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS abcxyz_results (
              period TEXT NOT NULL,
              item_code TEXT NOT NULL,
              abc CHAR(1) NOT NULL,
              xyz CHAR(1) NOT NULL,
              class TEXT NOT NULL,
              policy TEXT NOT NULL,
              stock NUMERIC NULL,
              turnover NUMERIC NULL,
              revenue NUMERIC NULL,
              min_qty NUMERIC NULL,
              max_qty NUMERIC NULL,
              item_name VARCHAR(255) NULL,
              updated_at TIMESTAMP NOT NULL DEFAULT now(),
              PRIMARY KEY (period, item_code)
            );
            """
        )
    )

    # Sync products catalog from ingested data (register/refresh items)
    try:
        if "item_code" in df.columns:
            # Prepare normalized fields
            codes = df["item_code"].astype(str).apply(lambda s: (s or "").strip().upper())
            names = (
                df["item_name"].astype(str).apply(lambda s: (s or "").strip())
                if "item_name" in df.columns
                else pd.Series([""] * len(df))
            )
            abcs = df["abc"].astype(str).apply(lambda s: (s or "").strip().upper()[:1]) if "abc" in df.columns else pd.Series([None] * len(df))
            xyzs = df["xyz"].astype(str).apply(lambda s: (s or "").strip().upper()[:1]) if "xyz" in df.columns else pd.Series([None] * len(df))

            payload: list[dict[str, Any]] = []
            for code, name, a, x in zip(codes, names, abcs, xyzs):
                if not code:
                    continue
                payload.append({
                    "code": str(code),
                    "name": str(name or code),
                    "abc": (a if a in {"A", "B", "C"} else None),
                    "xyz": (x if x in {"X", "Y", "Z"} else None),
                })
            if payload:
                sql = text(
                    """
                    INSERT INTO products (item_code, item_name, uom, active, abc, xyz, created_at, updated_at)
                    VALUES (:code, :name, 'EA', TRUE, :abc, :xyz, now(), now())
                    ON CONFLICT (item_code) DO UPDATE SET
                      item_name = CASE WHEN COALESCE(EXCLUDED.item_name,'') <> '' THEN EXCLUDED.item_name ELSE products.item_name END,
                      abc = COALESCE(EXCLUDED.abc, products.abc),
                      xyz = COALESCE(EXCLUDED.xyz, products.xyz),
                      active = TRUE,
                      updated_at = now()
                    """
                )
                # Chunk to avoid huge statements
                CHUNK = 500
                for i in range(0, len(payload), CHUNK):
                    chunk = payload[i:i+CHUNK]
                    await session.execute(sql, chunk)
    except Exception as _sync_exc:  # pragma: no cover - defensive
        # Do not fail ingest if product sync has issues
        pass
    # Ensure new columns exist for incremental deployments
    await session.execute(
        text(
            """
            ALTER TABLE IF EXISTS abcxyz_results
              ADD COLUMN IF NOT EXISTS min_qty NUMERIC,
              ADD COLUMN IF NOT EXISTS max_qty NUMERIC,
              ADD COLUMN IF NOT EXISTS item_name VARCHAR(255);
            """
        )
    )

    upsert = text(
        """
        INSERT INTO abcxyz_results (period, item_code, abc, xyz, class, policy, stock, turnover, revenue, min_qty, max_qty, item_name)
        VALUES (:period, :item_code, :abc, :xyz, :class, :policy, :stock, :turnover, :revenue, :min_qty, :max_qty, :item_name)
        ON CONFLICT (period, item_code) DO UPDATE SET
          abc=EXCLUDED.abc,
          xyz=EXCLUDED.xyz,
          class=EXCLUDED.class,
          policy=EXCLUDED.policy,
          stock=COALESCE(EXCLUDED.stock, abcxyz_results.stock),
          turnover=COALESCE(EXCLUDED.turnover, abcxyz_results.turnover),
          revenue=COALESCE(EXCLUDED.revenue, abcxyz_results.revenue),
          min_qty=COALESCE(EXCLUDED.min_qty, abcxyz_results.min_qty),
          max_qty=COALESCE(EXCLUDED.max_qty, abcxyz_results.max_qty),
          item_name=COALESCE(EXCLUDED.item_name, abcxyz_results.item_name),
          updated_at=now()
        ;
        """
    )

    rows = df.to_dict(orient="records")
    
    def as_num(v: Any) -> Any:
        try:
            import math
            import pandas as _pd  # type: ignore
        except Exception:  # pragma: no cover - fallback
            _pd = None  # type: ignore
        # Treat empty strings and NaN as None
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        try:
            # pandas NaN check if available
            if _pd is not None and _pd.isna(v):  # type: ignore[attr-defined]
                return None
        except Exception:
            pass
        try:
            # Let DB handle numeric casting; keep as original if already numeric
            if isinstance(v, (int, float)):
                if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
                    return None
                return v
            # Try to parse from string
            return float(str(v).strip())
        except Exception:
            return None
    cnt = 0
    for r in rows:
        abc_val = str(r.get("abc", "")).strip()[:1].upper()
        xyz_val = str(r.get("xyz", "")).strip()[:1].upper()
        # Compute class/policy when not provided
        provided_class = str(r.get("class", "")).strip()
        comp_class = provided_class.upper() if provided_class else f"{abc_val}{xyz_val}"
        provided_policy = str(r.get("policy", "")).strip()
        derived_policy = provided_policy or POLICY_DEFAULTS.get(comp_class, "Politica estandar")

        payload = {
            "period": period,
            "item_code": str(r.get("item_code", "")),
            "abc": abc_val,
            "xyz": xyz_val,
            "class": comp_class,
            "policy": derived_policy,
            "stock": as_num(r.get("stock")),
            "turnover": as_num(r.get("turnover")),
            "revenue": as_num(r.get("revenue")),
            "min_qty": as_num(r.get("min_qty")),
            "max_qty": as_num(r.get("max_qty")),
            "item_name": (str(r.get("item_name") or "").strip())[:255] or None,
        }
        if not payload["item_code"]:
            continue
        await session.execute(upsert, payload)
        cnt += 1
    await session.commit()
    return {"status": "ok", "rows": cnt, "period": period}


@router.get("/kpi/sale_rate")
async def kpi_sale_rate(
    period: str | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Compute KPI: Salidas/Disponibles for a given period.

    - Numerator: total OUTBOUND qty from movement table within day (or month range).
    - Denominator: SUM(stock) from abcxyz_results for the given `period` value.
    """
    require_role(user, "operator")

    # Resolve period: use latest if not provided
    if not period:
        if not await _table_exists(session):
            raise HTTPException(status_code=404, detail="No hay datos ABC-XYZ")
        row = await session.execute(text("SELECT period FROM abcxyz_results ORDER BY updated_at DESC LIMIT 1"))
        period = row.scalar()
        if not period:
            raise HTTPException(status_code=404, detail="No hay periodo disponible")

    # Denominator from abcxyz_results (exact match on period string)
    denom_row = await session.execute(
        text("SELECT COALESCE(SUM(stock), 0) FROM abcxyz_results WHERE period=:p"),
        {"p": period},
    )
    available_stock = float(denom_row.scalar() or 0.0)

    # Numerator from movement (inventory_simple) or fallback to moves SO
    date_from, date_to = _parse_period_to_range(period)
    outbound_qty = 0.0
    used_source = None

    if await _table_exists_name(session, "movement") and date_from and date_to:
        used_source = "movement"
        rs = await session.execute(
            text(
                """
                SELECT COALESCE(SUM(qty), 0)
                  FROM movement
                 WHERE type='OUTBOUND'
                   AND created_at >= :df AND created_at < :dt
                """
            ),
            {"df": date_from, "dt": date_to},
        )
        outbound_qty = float(rs.scalar() or 0.0)
    elif await _table_exists_name(session, "move_lines") and await _table_exists_name(session, "moves") and date_from and date_to:
        used_source = "moves"
        rs = await session.execute(
            text(
                """
                SELECT COALESCE(SUM(ml.qty_confirmed), 0)
                  FROM move_lines ml
                  JOIN moves m ON m.id = ml.move_id
                 WHERE m.doc_type='SO'
                   AND m.updated_at >= :df AND m.updated_at < :dt
                   AND m.status IN ('approved','pending')
                """
            ),
            {"df": date_from, "dt": date_to},
        )
        outbound_qty = float(rs.scalar() or 0.0)
    else:
        used_source = "unknown"

    rate = float(outbound_qty) / float(available_stock if available_stock > 0 else 1.0)
    return {
        "period": period,
        "source": used_source,
        "outbound_qty": outbound_qty,
        "available_stock": available_stock,
        "rate": rate,
    }


# ------------------------------
# Perfect Order Performance (POP)
# ------------------------------

@router.post("/orders/ingest")
async def orders_ingest(
    file: UploadFile = File(...),
    period: str = Form(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Ingest orders quality dataset for POP KPI.

    Expected columns (CSV/XLSX; flexible names supported):
    - order_id
    - promised_at (datetime)
    - delivered_at (datetime)
    - complete (bool)
    - damaged (bool)
    - misprocessed (bool)
    """
    require_role(user, "supervisor")
    if not period:
        raise HTTPException(status_code=400, detail="period requerido")

    # Read file
    name = (file.filename or "").lower()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacio")
    import pandas as pd  # local import
    from io import BytesIO, StringIO
    try:
        if name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(BytesIO(content))
        else:
            try:
                df = pd.read_csv(StringIO(content.decode("utf-8")))
            except UnicodeDecodeError:
                df = pd.read_csv(StringIO(content.decode("latin-1")))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el archivo: {exc}")

    df.columns = [str(c).strip().lower() for c in df.columns]

    # Column mapping
    def _n(s: str) -> str:
        return str(s).lower().replace(" ", "").replace("-", "").replace("_", "")

    norm = {_n(c): c for c in df.columns}
    def _find(*alts: str) -> str | None:
        for a in alts:
            if _n(a) in norm:
                return norm[_n(a)]
        return None

    col_order = _find("order_id", "order", "pedido", "orderid", "id")
    col_prom = _find("promised_at", "promised", "promesado", "fecha_promesa")
    col_deliv = _find("delivered_at", "delivered", "entregado", "fecha_entrega")
    col_comp = _find("complete", "completo", "fulfilled", "fullfilled")
    col_dmg = _find("damaged", "defectuoso", "dañado", "daniado")
    col_misp = _find("misprocessed", "maltramitado", "wrong", "errorproceso")

    if not col_order:
        raise HTTPException(status_code=400, detail="Columna order_id requerida")

    # Ensure destination table exists
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS orders_kpi (
              period TEXT NOT NULL,
              order_id TEXT NOT NULL,
              promised_at TIMESTAMP NULL,
              delivered_at TIMESTAMP NULL,
              complete BOOLEAN NULL,
              damaged BOOLEAN NULL,
              misprocessed BOOLEAN NULL,
              created_at TIMESTAMP NOT NULL DEFAULT now(),
              updated_at TIMESTAMP NOT NULL DEFAULT now(),
              PRIMARY KEY (period, order_id)
            )
            """
        )
    )

    def as_bool(v: Any) -> bool | None:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in {"1", "true", "t", "yes", "y", "si", "sí"}:
            return True
        if s in {"0", "false", "f", "no", "n"}:
            return False
        return None

    def as_dt(v: Any):
        if v is None or str(v).strip() == "":
            return None
        import pandas as pd
        try:
            d = pd.to_datetime(v, errors="coerce")
            if pd.isna(d):
                return None
            # Convert pandas Timestamp to python datetime
            return d.to_pydatetime()
        except Exception:
            return None

    rows = []
    for _, r in df.iterrows():
        order_id = str(r.get(col_order, "")).strip()
        if not order_id:
            continue
        rows.append(
            {
                "period": period,
                "order_id": order_id,
                "promised_at": as_dt(r.get(col_prom)) if col_prom else None,
                "delivered_at": as_dt(r.get(col_deliv)) if col_deliv else None,
                "complete": as_bool(r.get(col_comp)) if col_comp else None,
                "damaged": as_bool(r.get(col_dmg)) if col_dmg else None,
                "misprocessed": as_bool(r.get(col_misp)) if col_misp else None,
            }
        )

    if not rows:
        raise HTTPException(status_code=400, detail="No hay filas para importar")

    upsert = text(
        """
        INSERT INTO orders_kpi(period, order_id, promised_at, delivered_at, complete, damaged, misprocessed)
        VALUES (:period, :order_id, :promised_at, :delivered_at, :complete, :damaged, :misprocessed)
        ON CONFLICT (period, order_id) DO UPDATE SET
          promised_at=COALESCE(EXCLUDED.promised_at, orders_kpi.promised_at),
          delivered_at=COALESCE(EXCLUDED.delivered_at, orders_kpi.delivered_at),
          complete=COALESCE(EXCLUDED.complete, orders_kpi.complete),
          damaged=COALESCE(EXCLUDED.damaged, orders_kpi.damaged),
          misprocessed=COALESCE(EXCLUDED.misprocessed, orders_kpi.misprocessed),
          updated_at=now()
        ;
        """
    )
    CHUNK = 500
    for i in range(0, len(rows), CHUNK):
        await session.execute(upsert, rows[i:i+CHUNK])
    await session.commit()
    return {"status": "ok", "rows": len(rows), "period": period}


@router.get("/kpi/perfect_order")
async def kpi_perfect_order(
    period: str | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, "operator")

    # If the table is not present yet, return zeros gracefully
    if not await _table_exists_name(session, "orders_kpi"):
        return {"period": period, "total": 0, "late": 0, "not_complete": 0, "damaged": 0, "misprocessed": 0, "faults": 0, "pop": 0.0}

    # choose period
    if not period:
        if await _table_exists_name(session, "orders_kpi"):
            rs = await session.execute(text("SELECT period FROM orders_kpi ORDER BY updated_at DESC LIMIT 1"))
            period = rs.scalar()
            if not period:
                return {"period": None, "total": 0, "late": 0, "not_complete": 0, "damaged": 0, "misprocessed": 0, "faults": 0, "pop": 0.0}

    # compute counts on period
    total_rs = await session.execute(text("SELECT COUNT(*) FROM orders_kpi WHERE period=:p"), {"p": period})
    total = int(total_rs.scalar() or 0)
    if total == 0:
        return {"period": period, "total": 0, "late": 0, "not_complete": 0, "damaged": 0, "misprocessed": 0, "faults": 0, "pop": 0.0}

    late_rs = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM orders_kpi
             WHERE period=:p
               AND promised_at IS NOT NULL
               AND (delivered_at IS NULL OR delivered_at > promised_at)
            """
        ),
        {"p": period},
    )
    late = int(late_rs.scalar() or 0)

    not_complete_rs = await session.execute(
        text("SELECT COUNT(*) FROM orders_kpi WHERE period=:p AND COALESCE(complete, false) IS FALSE"),
        {"p": period},
    )
    not_complete = int(not_complete_rs.scalar() or 0)

    dmg_rs = await session.execute(
        text("SELECT COUNT(*) FROM orders_kpi WHERE period=:p AND COALESCE(damaged, false) IS TRUE"),
        {"p": period},
    )
    damaged = int(dmg_rs.scalar() or 0)

    misp_rs = await session.execute(
        text("SELECT COUNT(*) FROM orders_kpi WHERE period=:p AND COALESCE(misprocessed, false) IS TRUE"),
        {"p": period},
    )
    misprocessed = int(misp_rs.scalar() or 0)

    faults = min(total, late + not_complete + damaged + misprocessed)
    pop = (total - faults) / total if total else 0.0
    return {"period": period, "total": total, "late": late, "not_complete": not_complete, "damaged": damaged, "misprocessed": misprocessed, "faults": faults, "pop": pop}


@router.get("/latest")
async def latest(
    session: AsyncSession = Depends(get_session),
    limit: int = 500,
    offset: int = 0,
    user=Depends(get_current_user),
) -> dict[str, Any]:
    # If table was not created yet, return empty payload gracefully
    if not await _table_exists(session):
        return {
            "period": None,
            "updated_at": None,
            "summary": {"abc": {}, "xyz": {}, "matrix": [], "kpi": {}},
            "rows": [],
        }

    period_row = await session.execute(
        text("SELECT period FROM abcxyz_results ORDER BY updated_at DESC LIMIT 1")
    )
    period = period_row.scalar()
    if not period:
        return {
            "period": None,
            "updated_at": None,
            "summary": {"abc": {}, "xyz": {}, "matrix": [], "kpi": {}},
            "rows": [],
        }

    updated_at_row = await session.execute(
        text("SELECT MAX(updated_at) FROM abcxyz_results WHERE period=:p"), {"p": period}
    )
    updated_at = updated_at_row.scalar()

    # Prefer live stock from inventory_balance (sum by item_code). Fallback to stored snapshot.
    rows: list[dict[str, Any]]
    if await _table_exists_name(session, "inventory_balance"):
        rows_rs = await session.execute(
            text(
                """
                SELECT r.item_code,
                       r.abc,
                       r.xyz,
                       r.class,
                       r.policy,
                       r.min_qty,
                       r.max_qty,
                       COALESCE(r.item_name, p.item_name) AS item_name,
                       COALESCE(ls.stock, 0) AS stock
                FROM abcxyz_results r
                LEFT JOIN products p ON p.item_code = r.item_code
                LEFT JOIN (
                    SELECT item_code, COALESCE(SUM(qty), 0) AS stock
                    FROM inventory_balance
                    GROUP BY item_code
                ) ls ON ls.item_code = r.item_code
                WHERE r.period=:p
                ORDER BY r.item_code
                LIMIT :l OFFSET :o
                """
            ),
            {"p": period, "l": limit, "o": offset},
        )
        rows = [dict(r._mapping) for r in rows_rs]
    else:
        rows_rs = await session.execute(
            text(
                """
                SELECT r.item_code,
                       r.abc,
                       r.xyz,
                       r.class,
                       r.policy,
                       r.min_qty,
                       r.max_qty,
                       COALESCE(r.item_name, p.item_name) AS item_name,
                       r.stock
                FROM abcxyz_results r
                LEFT JOIN products p ON p.item_code = r.item_code
                WHERE r.period=:p
                ORDER BY r.item_code
                LIMIT :l OFFSET :o
                """
            ),
            {"p": period, "l": limit, "o": offset},
        )
        rows = [dict(r._mapping) for r in rows_rs]

    abc_rs = await session.execute(
        text("SELECT abc, COUNT(*) FROM abcxyz_results WHERE period=:p GROUP BY abc"),
        {"p": period},
    )
    abc = {k: v for k, v in abc_rs}

    xyz_rs = await session.execute(
        text("SELECT xyz, COUNT(*) FROM abcxyz_results WHERE period=:p GROUP BY xyz"),
        {"p": period},
    )
    xyz = {k: v for k, v in xyz_rs}

    matrix_rs = await session.execute(
        text(
            """
            SELECT abc, xyz, COUNT(*) AS count
            FROM abcxyz_results WHERE period=:p GROUP BY abc, xyz
            """
        ),
        {"p": period},
    )
    matrix = [dict(m._mapping) for m in matrix_rs]

    total = int(sum(abc.values())) if abc else 0
    kpi = {
        "total": total,
        "percentA": round(100 * (abc.get("A", 0) / total), 1) if total else 0.0,
        "percentB": round(100 * (abc.get("B", 0) / total), 1) if total else 0.0,
        "percentC": round(100 * (abc.get("C", 0) / total), 1) if total else 0.0,
    }

    return {
        "period": period,
        "updated_at": updated_at,
        "summary": {"abc": abc, "xyz": xyz, "matrix": matrix, "kpi": kpi},
        "rows": rows,
    }


@router.get("/template-from-products")
async def template_from_products(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Export a CSV template for ABC-XYZ starting from current products.

    Columns: item_code, item_name, abc, xyz, stock
    """
    require_role(user, "operator")
    # Aggregate current stock by item_code (optional)
    rs = await session.execute(
        text(
            """
            SELECT p.item_code,
                   p.item_name,
                   COALESCE(SUM(s.qty), 0) AS stock
            FROM products p
            LEFT JOIN stock s ON s.item_code = p.item_code
            WHERE p.active IS TRUE
            GROUP BY p.item_code, p.item_name
            ORDER BY p.item_name
            """
        )
    )
    rows = rs.all()
    import csv, io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["item_code", "item_name", "abc", "xyz", "stock"])  # abc/xyz left blank for user to fill
    for code, name, stock in rows:
        writer.writerow([code, name, "", "", stock])
    from fastapi import Response
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=abcxyz_template.csv"},
    )


@router.get("/table")
async def table(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    limit: int = 1000,
    offset: int = 0,
) -> list[dict[str, Any]]:
    # Return latest period rows for UI table (no turnover/revenue)
    period_row = await session.execute(
        text("SELECT period FROM abcxyz_results ORDER BY updated_at DESC LIMIT 1")
    )
    period = period_row.scalar()
    if not period:
        return []
    rs = await session.execute(
        text(
            """
            SELECT r.item_code,
                   COALESCE(r.item_name, p.item_name) AS item_name,
                   r.abc,
                   r.xyz,
                   r.class,
                   r.policy,
                   r.min_qty,
                   r.max_qty,
                   r.stock
            FROM abcxyz_results r
            LEFT JOIN products p ON p.item_code = r.item_code
            WHERE r.period=:p
            ORDER BY r.item_code
            LIMIT :l OFFSET :o
            """
        ),
        {"p": period, "l": limit, "o": offset},
    )
    return [dict(m._mapping) for m in rs]


@router.get("/item/{code}")
async def item_lookup(
    code: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    # If table is absent, return empty result
    if not await _table_exists(session):
        return {}
    rs = await session.execute(
        text(
            """
            SELECT period, abc, xyz, class, policy, stock, turnover, revenue, updated_at
            FROM abcxyz_results WHERE item_code=:c
            ORDER BY updated_at DESC LIMIT 1
            """
        ),
        {"c": code},
    )
    row = rs.mappings().first()
    return dict(row) if row else {}
