# -*- coding: utf-8 -*-
"""
ABC–XYZ + Política de stock (sin inventario actual)
Entradas esperadas:
  --prices  : XLSX/CSV con ItemCode, ItemName, AvgPrice (nombres libres; se normalizan)
  --guias   : XLSX/CSV con movimientos (consumos) de guías
  --salidas : XLSX/CSV con movimientos (consumos) de salidas
Alternativa legacy:
  --issues  : único archivo de movimientos si no se entregan --guias/--salidas

Salida:
  ./output/csv/abcxyz_master.csv
  ./output/csv/monthly_demand.csv
  ./output/csv/reorder_alerts.csv
  ./output/abcxyz_results.xlsx
"""
from pathlib import Path
import pandas as pd, numpy as np, re, unicodedata, argparse, sys, yaml

# ──────────────────────────────────────────────────────────────────────────────
# Parámetros
# ──────────────────────────────────────────────────────────────────────────────
OUT_DIR = Path("./output")
OUT_EXCEL = "abcxyz_results.xlsx"

ABC_CUTS = (0.80, 0.95)         # 80-15-5
XYZ_CUTS = (0.50, 1.00)         # CV thresholds: X <=0.5, Y <=1.0, else Z

Z_BY_ABC = {"A": 1.96, "B": 1.65, "C": 1.28}
Z_BY_XYZ = {"X": 1.65, "Y": 1.44, "Z": 1.28}
Z_DEFAULT = 1.65
LEAD_BY_ABC = {"A": 20, "B": 15, "C": 10}
LT_DEFAULT = 15
ORDER_COST = 15000.0            # costo por orden
HOLDING_RATE = 0.25             # % anual de costo de mantener
USE_EOQ = True

# ──────────────────────────────────────────────────────────────────────────────
# Utilidades
# ──────────────────────────────────────────────────────────────────────────────
def slug(t: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_",
                  unicodedata.normalize("NFKD", str(t))
                  .encode("ascii", "ignore").decode()).strip("_").lower()

def eoq(D, S, H, C):
    D, S, H, C = float(D or 0), float(S or 0), float(H or 0), float(C or 0)
    if D <= 0 or S <= 0 or (H*C) <= 0:
        return 0.0
    return ((2.0 * D * S) / (H * C)) ** 0.5

def pick_z(a: str, x: str) -> float:
    z = Z_DEFAULT
    if a in Z_BY_ABC:
        z = Z_BY_ABC[a]
    if x in Z_BY_XYZ:
        z = max(z, Z_BY_XYZ[x])
    return float(z)

# ──────────────────────────────────────────────────────────────────────────────
# Normalización de entradas
# ──────────────────────────────────────────────────────────────────────────────
def normalize_prices(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=lambda c: slug(c))
    canon = {
        "numero_de_articulo": "itemcode",
        "codigo": "itemcode",
        "itemcode": "itemcode",
        "descripcion_del_articulo": "itemname",
        "descripcion": "itemname",
        "itemname": "itemname",
        "precio_promedio": "avgprice",
        "precio_de_articulo": "avgprice",
        "precio_articulo": "avgprice",
        "avgprice": "avgprice",
        "precio": "avgprice",
    }
    df = df.rename(columns={k: v for k, v in canon.items() if k in df.columns})
    if "itemcode" not in df.columns:
        raise ValueError("No se encontró columna itemcode en precios")
    df["itemcode"] = df["itemcode"].astype(str).str.strip().str.upper()
    if "avgprice" not in df.columns:
        df["avgprice"] = 1.0
    df["avgprice"] = pd.to_numeric(df["avgprice"], errors="coerce").fillna(1.0).clip(lower=0.0)
    if "itemname" not in df.columns:
        df["itemname"] = ""
    df = df.drop_duplicates("itemcode")
    return df[["itemcode", "itemname", "avgprice"]]

def normalize_moves(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=lambda c: slug(c))
    item_col = next((c for c in df.columns if c.startswith(("numero_de_articulo", "codigo", "itemcode", "sku", "item"))), None)
    if item_col is None:
        raise ValueError("No se encontró columna SKU en movimientos")
    date_col = next((c for c in df.columns if "fecha" in c or c.startswith(("date", "postingdate", "docdate"))), None)
    if date_col is None:
        raise ValueError("No se encontró columna fecha en movimientos")
    qty_col = next((c for c in df.columns if c in ("quantity", "qty", "cantidad", "cantidad_de_articulos", "qty_out")), None)

    cols = [item_col, date_col] + ([qty_col] if qty_col else [])
    df = df[cols].rename(columns={item_col: "itemcode", date_col: "date"})
    df = df[df["itemcode"].notna() & df["itemcode"].astype(str).str.strip().ne("")]
    df["itemcode"] = df["itemcode"].astype(str).str.strip().str.upper()
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    df = df[df["date"].notna()].copy()
    if qty_col:
        df["qty"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0).clip(lower=0)
    else:
        df["qty"] = 1
    return df[["itemcode", "qty", "date"]]

# Reference helpers for supplier lists (HELI/TVH)
def codes_set_from_df(df: pd.DataFrame) -> set:
    df = df.rename(columns=lambda c: slug(c))
    item_col = next((c for c in df.columns if c.startswith(("numero_de_articulo", "codigo", "itemcode", "sku", "item"))), None)
    if item_col is None:
        return set()
    s = df[item_col].astype(str).str.strip().str.upper()
    return set(s[s.ne("")])

def load_supplier_sets(args):
    heli_set, tvh_set = set(), set()
    if getattr(args, "heli", None):
        p = args.heli
        try:
            if str(p).lower().endswith((".xlsx", ".xlsm", ".xls")):
                dfh = pd.read_excel(p, engine="openpyxl")
            else:
                dfh = pd.read_csv(p)
            # incluir todos los cdigos del archivo HELI (independiente de Nombre extranjero)
            heli_set = codes_set_from_df(dfh)
        except Exception:
            heli_set = set()
    if getattr(args, "tvh", None):
        p = args.tvh
        try:
            if str(p).lower().endswith((".xlsx", ".xlsm", ".xls")):
                dft = pd.read_excel(p, engine="openpyxl")
            else:
                dft = pd.read_csv(p)
            # si existe columna "Nombre extranjero", quedarnos con filas que indiquen TVH
            dft_cols = {slug(c): c for c in dft.columns}
            ne_col = dft_cols.get("nombre_extranjero")
            if ne_col:
                mask_tvh = dft[ne_col].astype(str).str.contains(r"\btvh\b", case=False, regex=True)
                dft2 = dft[mask_tvh] if mask_tvh.any() else dft
                tvh_set = codes_set_from_df(dft2)
            else:
                tvh_set = codes_set_from_df(dft)
        except Exception:
            tvh_set = set()
    return heli_set, tvh_set

# ──────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ──────────────────────────────────────────────────────────────────────────────
def load_inputs(args):
    if args.source == "excel":
        prices_df = normalize_prices(pd.read_excel(args.prices, engine="openpyxl")) if args.prices else pd.DataFrame(columns=["itemcode","itemname","avgprice"])
        if args.guias or args.salidas:
            guias_df = normalize_moves(pd.read_excel(args.guias, engine="openpyxl")) if args.guias else pd.DataFrame(columns=["itemcode","qty","date"])
            sal_df   = normalize_moves(pd.read_excel(args.salidas, engine="openpyxl")) if args.salidas else pd.DataFrame(columns=["itemcode","qty","date"])
            issues_df = pd.concat([guias_df, sal_df], ignore_index=True)
        elif args.issues:
            issues_df = normalize_moves(pd.read_excel(args.issues, engine="openpyxl"))
        else:
            raise SystemExit("Faltan movimientos: provee --guias y/o --salidas, o --issues")
        return prices_df, issues_df

    if args.source == "csv":
        prices_df = normalize_prices(pd.read_csv(args.prices)) if args.prices else pd.DataFrame(columns=["itemcode","itemname","avgprice"])
        if args.guias or args.salidas:
            guias_df = normalize_moves(pd.read_csv(args.guias)) if args.guias else pd.DataFrame(columns=["itemcode","qty","date"])
            sal_df   = normalize_moves(pd.read_csv(args.salidas)) if args.salidas else pd.DataFrame(columns=["itemcode","qty","date"])
            issues_df = pd.concat([guias_df, sal_df], ignore_index=True)
        elif args.issues:
            issues_df = normalize_moves(pd.read_csv(args.issues))
        else:
            raise SystemExit("Faltan movimientos: provee --guias y/o --salidas, o --issues")
        return prices_df, issues_df

    if args.source == "sql":
        cfg = {}
        try:
            with open("config.yaml", "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except FileNotFoundError:
            pass
        try:
            import pyodbc
        except Exception as e:
            raise SystemExit(f"pyodbc no disponible: {e}")
        s = cfg.get("sql", {})
        parts = [
            f"DRIVER={s.get('driver','{{ODBC Driver 18 for SQL Server}}')}",
            f"SERVER={s.get('server','localhost')}",
            f"DATABASE={s.get('database','SBODemoCL')}",
            f"UID={s.get('user','')}",
            f"PWD={s.get('password','')}",
        ]
        if str(s.get("trustservercertificate","yes")).lower() in ("yes","true","1"):
            parts.append("TrustServerCertificate=yes")
        cn = pyodbc.connect(";".join(parts)+";")

        prices_df = pd.read_sql("SELECT i.ItemCode, i.ItemName, i.AvgPrice AS avgprice FROM OITM i;", cn)
        prices_df = prices_df.rename(columns={"ItemCode":"itemcode","ItemName":"itemname"})
        prices_df = normalize_prices(prices_df)

        issues_df = pd.read_sql("""
            SELECT l.ItemCode, CAST(h.DocDate AS date) AS DocDate,
                   l.Quantity AS Quantity
            FROM IGE1 l
            JOIN OIGE h ON h.DocEntry = l.DocEntry
            WHERE h.DocDate >= DATEADD(month,-12,CAST(GETDATE() AS date));
        """, cn)
        cn.close()
        issues_df = issues_df.rename(columns={"ItemCode":"itemcode","DocDate":"date","Quantity":"qty"})
        issues_df = normalize_moves(issues_df)
        return prices_df, issues_df

    raise SystemExit("Fuente no soportada")

# ──────────────────────────────────────────────────────────────────────────────
# Núcleo ABC–XYZ
# ──────────────────────────────────────────────────────────────────────────────
def run(prices_df: pd.DataFrame, issues_df: pd.DataFrame, heli_set=None, tvh_set=None):
    prices_df = prices_df.copy()
    issues_df = issues_df.copy()

    if prices_df.empty:
        prices_df = pd.DataFrame({"itemcode": issues_df["itemcode"].unique(), "itemname": "", "avgprice": 1.0})

    prices_df["avgprice"] = pd.to_numeric(prices_df["avgprice"], errors="coerce").fillna(1.0).clip(lower=0.0)

    cons = issues_df.merge(prices_df[["itemcode","itemname","avgprice"]], on="itemcode", how="left")
    cons["avgprice"] = cons["avgprice"].fillna(1.0)
    cons["valor"] = cons["qty"] * cons["avgprice"]

    # ABC por valor
    agg = (cons.groupby("itemcode", as_index=False)
              .agg(itemname=("itemname","first"),
                   valor=("valor","sum"),
                   unidades=("qty","sum"))
              .sort_values("valor", ascending=False)
              .reset_index(drop=True))
    total_valor = float(agg["valor"].sum())
    agg["pct"] = (agg["valor"].cumsum()/total_valor) if total_valor > 0 else 0.0
    cutA, cutB = ABC_CUTS
    agg["ABC"] = pd.cut(agg["pct"], bins=[0, cutA, cutB, 1], labels=list("ABC"), include_lowest=True).astype(str)

    # XYZ por CV mensual
    mens = (issues_df.set_index("date")
             .groupby("itemcode")["qty"]
             .resample("ME").sum()
             .unstack(fill_value=0))
    mean = mens.mean(axis=1).replace(0, np.nan)
    std  = mens.std(axis=1, ddof=1)
    cv   = (std/mean).replace([np.inf, -np.inf], np.nan)
    xyz  = pd.Series("Z", index=mens.index)
    xyz[(cv.notna()) & (cv <= XYZ_CUTS[0])] = "X"
    xyz[(cv.notna()) & (cv > XYZ_CUTS[0]) & (cv <= XYZ_CUTS[1])] = "Y"

    # Maestro
    master = pd.DataFrame({
        "item_code": mens.index,
        "item_name": agg.set_index("itemcode")["itemname"].reindex(mens.index),
        "monthly_mean": mens.mean(axis=1).values,
        "monthly_std":  mens.std(axis=1, ddof=1).values,
        "annual_qty":   mens.sum(axis=1).values,
        "ABC": agg.set_index("itemcode")["ABC"].reindex(mens.index).values,
        "XYZ": xyz.reindex(mens.index).values
    }).set_index("item_code")

    unit_cost = prices_df.set_index("itemcode")["avgprice"].reindex(master.index).fillna(1.0)
    master["unit_cost"] = unit_cost
    master["ACV"] = master["annual_qty"].fillna(0) * master["unit_cost"].fillna(0)

    # Política simple (ROP/SS/EOQ) sobre demanda diaria aproximada
    daily_mean = master["monthly_mean"] / 30.0
    daily_std  = master["monthly_std"]  / 30.0
    # Supplier resolution with HELI priority (lists + name contains 'heli')
    heli_set = heli_set or set()
    tvh_set = tvh_set or set()
    name_contains_heli = master["item_name"].astype(str).str.contains(r"\bheli\b", case=False, regex=True)
    supplier = pd.Series("NACIONAL", index=master.index, dtype=object)
    supplier.loc[master.index.isin(tvh_set)] = "TVH"
    supplier.loc[master.index.isin(heli_set) | name_contains_heli] = "HELI"
    # Lead time by supplier (config override if present)
    lt_map_default = {"HELI": 90, "TVH": 45, "NACIONAL": 3}
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        pol = cfg.get("policy", {})
        lt_map_cfg = pol.get("lead_time_by_supplier")
        if isinstance(lt_map_cfg, dict) and lt_map_cfg:
            lt_map_norm = {str(k).strip().upper(): int(v) for k, v in lt_map_cfg.items()}
            lead_time = supplier.astype(str).str.upper().map(lt_map_norm).fillna(LT_DEFAULT)
        else:
            lead_time = supplier.map(lt_map_default).fillna(LT_DEFAULT)
    except FileNotFoundError:
        lead_time = supplier.map(lt_map_default).fillna(LT_DEFAULT)
    z_level    = [pick_z(a, x) for a, x in zip(master["ABC"], master["XYZ"])]

    master["z_level"] = z_level
    master["lead_time_days"] = lead_time
    master["supplier"] = supplier
    master["SS"]  = master["z_level"] * np.sqrt(master["lead_time_days"]) * daily_std.fillna(0)
    master["ROP"] = daily_mean.fillna(0) * master["lead_time_days"] + master["SS"]

    if USE_EOQ:
        master["EOQ"] = [eoq(D, ORDER_COST, HOLDING_RATE, C) for D, C in zip(master["annual_qty"], master["unit_cost"])]
    else:
        master["EOQ"] = 0.0

    master["SMIN"] = master["ROP"]
    master["SMAX"] = master["ROP"] + master["EOQ"]

    # Sin inventario actual: OnHand = 0 para referencia
    master["OnHand"] = 0.0
    master["BelowROP"] = master["OnHand"] < master["ROP"]

    # Salidas
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "csv").mkdir(parents=True, exist_ok=True)

    monthly_out = mens.reset_index()
    master_out  = master.reset_index().sort_values(["ABC","XYZ","annual_qty"], ascending=[True, True, False])
    # No exponer proveedor en salidas (solo lead_time_days)
    master_out = master_out.drop(columns=["supplier"], errors="ignore")
    alerts_out  = master_out[master_out["BelowROP"]].copy()
    alerts_out["SuggestedOrderQty"] = (alerts_out["SMAX"] - alerts_out["OnHand"]).clip(lower=0.0)

    monthly_out.to_csv(OUT_DIR / "csv/monthly_demand.csv", index=False, encoding="utf-8")
    master_out.to_csv(OUT_DIR / "csv/abcxyz_master.csv", index=False, encoding="utf-8")
    alerts_out.to_csv(OUT_DIR / "csv/reorder_alerts.csv", index=False, encoding="utf-8")

    with pd.ExcelWriter(OUT_DIR / OUT_EXCEL, engine="openpyxl") as xl:
        master_out.to_excel(xl, sheet_name="master", index=False)
        monthly_out.to_excel(xl, sheet_name="monthly_demand", index=False)
        alerts_out.to_excel(xl, sheet_name="reorder_alerts", index=False)

    print(f"OK | items={len(master_out)} | alerts={len(alerts_out)} | out={OUT_DIR}")

# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["excel","csv","sql"], default="excel")
    ap.add_argument("--prices")
    ap.add_argument("--issues")    # compatibilidad legacy
    ap.add_argument("--guias")     # NUEVO
    ap.add_argument("--salidas")   # NUEVO
    ap.add_argument("--heli")      # lista de items HELI
    ap.add_argument("--tvh")       # lista de items TVH
    args = ap.parse_args()

    prices_df, issues_df = load_inputs(args)
    heli_set, tvh_set = load_supplier_sets(args)
    if issues_df.empty:
        raise SystemExit("No hay movimientos válidos tras normalización")

    run(prices_df, issues_df, heli_set=heli_set, tvh_set=tvh_set)

if __name__ == "__main__":
    main()
