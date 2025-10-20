# -*- coding: utf-8 -*-
"""
Reporte ejecutivo ABC–XYZ con interpretación y recomendaciones (automático)

Lee:  /data/project/output/abcxyz_results.xlsx  (hojas: master, monthly_demand, reorder_alerts)
Escribe: /data/project/output/abcxyz_report.pdf

Requisitos:
  - reportlab
  - matplotlib
  - pandas, numpy
"""
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

# Matplotlib -> backend no interactivo
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ReportLab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
    PageBreak, Flowable, ListFlowable, ListItem
)

# ─────────────────────────────────────────────────────────────
# Rutas y estilo
# ─────────────────────────────────────────────────────────────
BASE_DIR   = Path("/data/project")
OUT_DIR    = BASE_DIR / "output"
XLSX_PATH  = OUT_DIR / "abcxyz_results.xlsx"
PDF_PATH   = OUT_DIR / "abcxyz_report.pdf"
ASSETS_DIR = BASE_DIR / "assets"
LOGO_PATH  = ASSETS_DIR / "logo.png"   # opcional
CHARTS_DIR = OUT_DIR / "_charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

PRIMARY = colors.HexColor("#0B5CAD")
ACCENT  = colors.HexColor("#2D3748")
LIGHT   = colors.HexColor("#F2F4F7")
MUTED   = colors.HexColor("#6B7280")

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
        base = "DejaVu"; bold = "DejaVu-Bold"
    except Exception:
        base = "Helvetica"; bold = "Helvetica-Bold"
    return base, bold

def build_styles():
    base, bold = register_fonts()
    ss = getSampleStyleSheet()
    normal = ParagraphStyle("N", parent=ss["Normal"], fontName=base, fontSize=9.5, leading=13)
    title  = ParagraphStyle("Title", parent=normal, fontName=bold, fontSize=24, leading=28, textColor=PRIMARY)
    h1     = ParagraphStyle("H1", parent=normal, fontName=bold, fontSize=14, leading=18, textColor=ACCENT)
    h2     = ParagraphStyle("H2", parent=normal, fontName=bold, fontSize=11.5, leading=14, textColor=ACCENT)
    smallR = ParagraphStyle("SmallR", parent=normal, alignment=TA_RIGHT, textColor=MUTED, fontSize=8.5)
    bullet = ParagraphStyle("Bullet", parent=normal, leftIndent=12, bulletIndent=0)
    return {"normal": normal, "title": title, "h1": h1, "h2": h2, "smallR": smallR, "bullet": bullet, "fontBase": base}

def fmt_int(x):
    try: return f"{int(round(float(x))):,}".replace(",", ".")
    except: return "0"

def fmt_money(x, symbol="$"):
    try: return f"{symbol} {int(round(float(x))):,}".replace(",", ".")
    except: return f"{symbol} 0"

def fig_to_png(fig, name: str) -> Path:
    p = CHARTS_DIR / name
    fig.savefig(p, bbox_inches="tight", dpi=180)
    plt.close(fig)
    return p

# ─────────────────────────────────────────────────────────────
# Gráficos
# ─────────────────────────────────────────────────────────────
def chart_top_acv(master_df, top_n=20) -> Path:
    d = master_df.sort_values("ACV", ascending=False).head(top_n)[["item_code","ACV"]].copy()
    d = d.iloc[::-1]
    fig = plt.figure(figsize=(10, 5.5))
    ax  = fig.add_subplot(111)
    ax.barh(d["item_code"], d["ACV"])
    ax.set_xlabel("ACV"); ax.set_ylabel("SKU"); ax.set_title("Top-20 por ACV")
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    for i, v in enumerate(d["ACV"].values):
        ax.text(v, i, fmt_int(v), va="center", fontsize=8)
    return fig_to_png(fig, "top_acv.png")

def chart_abcxyz_heat(master_df) -> Path:
    t = master_df.copy()
    t["ABC"] = t["ABC"].astype(str)
    t["XYZ"] = t["XYZ"].astype(str)
    pv = (t.pivot_table(index="ABC", columns="XYZ", values="item_code", aggfunc="count", fill_value=0)
            .reindex(index=list("ABC"), columns=list("XYZ")))
    fig = plt.figure(figsize=(6.5, 4.5))
    ax  = fig.add_subplot(111)
    im  = ax.imshow(pv.values, cmap="Blues")
    ax.set_xticks(range(pv.shape[1])); ax.set_xticklabels(pv.columns)
    ax.set_yticks(range(pv.shape[0])); ax.set_yticklabels(pv.index)
    ax.set_title("Distribución ABC × XYZ (conteo)")
    for i in range(pv.shape[0]):
        for j in range(pv.shape[1]):
            ax.text(j, i, int(pv.iloc[i, j]), ha="center", va="center", fontsize=10)
    return fig_to_png(fig, "abcxyz_heat.png")

# ─────────────────────────────────────────────────────────────
# Datos y KPIs
# ─────────────────────────────────────────────────────────────
def load_data():
    if not XLSX_PATH.exists():
        raise SystemExit(f"No existe {XLSX_PATH}")
    x = pd.ExcelFile(XLSX_PATH)
    master  = pd.read_excel(x, "master")
    monthly = pd.read_excel(x, "monthly_demand")
    alerts  = pd.read_excel(x, "reorder_alerts")
    return master, monthly, alerts

def compute_kpis(master: pd.DataFrame, alerts: pd.DataFrame):
    k = {}
    k["items"]   = len(master)
    k["alerts"]  = len(alerts)
    k["acv_tot"] = float(master["ACV"].fillna(0).sum())

    # participación por ABC y por AX/AZ/CX
    def share(mask):
        if len(master)==0: return 0.0
        return 100.0 * float(master.loc[mask, "ACV"].sum()) / float(master["ACV"].sum() or 1)

    master["ABC"] = master["ABC"].astype(str)
    master["XYZ"] = master["XYZ"].astype(str)

    k["pct_A_skus"]  = 100.0 * (master["ABC"]=="A").mean() if len(master) else 0.0
    k["pct_A_acv"]   = share(master["ABC"]=="A")
    k["pct_AX_skus"] = 100.0 * ((master["ABC"]=="A") & (master["XYZ"]=="X")).mean() if len(master) else 0.0
    k["pct_AX_acv"]  = share((master["ABC"]=="A") & (master["XYZ"]=="X"))
    k["pct_AZ_acv"]  = share((master["ABC"]=="A") & (master["XYZ"]=="Z"))
    k["pct_CZ_acv"]  = share((master["ABC"]=="C") & (master["XYZ"]=="Z"))
    k["top_sku"]     = (master.sort_values("ACV", ascending=False).head(1)["item_code"].astype(str).iloc[0]
                        if len(master) else "-")
    # Sugerido total (sumatoria de SuggestedOrderQty si existe; si no, SMAX - OnHand truncado a 0)
    try:
        if len(alerts):
            if "SuggestedOrderQty" in alerts.columns:
                k["sugerido_total"] = float(pd.to_numeric(alerts["SuggestedOrderQty"], errors="coerce").fillna(0).sum())
            else:
                smax = pd.to_numeric(alerts.get("SMAX", 0), errors="coerce").fillna(0)
                onh  = pd.to_numeric(alerts.get("OnHand", 0), errors="coerce").fillna(0)
                k["sugerido_total"] = float((smax - onh).clip(lower=0).sum())
        else:
            k["sugerido_total"] = 0.0
    except Exception:
        k["sugerido_total"] = 0.0
    return k

# ─────────────────────────────────────────────────────────────
# Reglas de negocio (texto automático)
# ─────────────────────────────────────────────────────────────
def build_interpretation(master: pd.DataFrame, k):
    lines = []

    # Narrativa de concentración
    lines.append(
        f"Los ítems clase <b>A</b> representan el {k['pct_A_skus']:.1f}% de los SKUs y concentran "
        f"el {k['pct_A_acv']:.1f}% del valor (ACV). Esto valida priorizar recursos en este grupo."
    )

    # Enfoques por cuadrante clave
    if k["pct_AX_acv"] >= 20:
        lines.append(
            f"Los <b>A×X</b> (alto valor y demanda estable) explican el {k['pct_AX_acv']:.1f}% del gasto. "
            "Recomendación: contratos marco, reposición frecuente y stock de seguridad alto con monitoreo semanal."
        )
    else:
        lines.append(
            f"Los <b>A×X</b> explican el {k['pct_AX_acv']:.1f}% del gasto. Mantener liderazgo en abastecimiento con SS medio-alto."
        )

    if k["pct_AZ_acv"] >= 10:
        lines.append(
            f"Los <b>A×Z</b> (alto valor y variabilidad alta) representan el {k['pct_AZ_acv']:.1f}% del gasto. "
            "Recomendación: reducir inventario especulativo; privilegiar compras a demanda y acuerdos de entrega rápida."
        )

    if k["pct_CZ_acv"] >= 5:
        lines.append(
            f"Los <b>C×Z</b> concentran el {k['pct_CZ_acv']:.1f}% del gasto. "
            "Revisión: descatalogar o pasar a bajo nivel con abastecimiento bajo pedido."
        )

    # Mensajes operativos genéricos por ABC×XYZ
    # Conteo por celda para reforzar foco
    pv_cnt = (master.assign(ABC=master["ABC"].astype(str), XYZ=master["XYZ"].astype(str))
                    .pivot_table(index="ABC", columns="XYZ", values="item_code", aggfunc="count", fill_value=0)
                    .reindex(index=list("ABC"), columns=list("XYZ")))
    ax_cnt = int(pv_cnt.loc["A","X"]) if "A" in pv_cnt.index and "X" in pv_cnt.columns else 0
    az_cnt = int(pv_cnt.loc["A","Z"]) if "A" in pv_cnt.index and "Z" in pv_cnt.columns else 0
    lines.append(
        f"Hay <b>{ax_cnt}</b> ítems <b>A×X</b> (candidatos a cobertura continua) y <b>{az_cnt}</b> ítems <b>A×Z</b> "
        "(candidatos a compra a demanda con lead-time pactado)."
    )

    return lines

def policy_table():
    rows = [
        ["A×X", "Abastecimiento continuo; SS alto; revisión semanal; contratos marco/proveedor preferente."],
        ["A×Y", "SS medio-alto; forecast trimestral; revisión quincenal."],
        ["A×Z", "Compra a demanda; mínimos bajos; acuerdos de entrega rápida; evitar sobrestock."],
        ["B×X", "SS medio; reposición cíclica; forecast semestral."],
        ["B×Y", "SS medio-bajo; revisión mensual."],
        ["B×Z", "Compra planificada puntual; revisar obsolescencia."],
        ["C×X", "Reposición automática con lote pequeño; bajo esfuerzo."],
        ["C×Y", "Revisión bimensual; niveles mínimos."],
        ["C×Z", "Descontinuar o abastecimiento bajo pedido según criticidad."],
    ]
    data = [["Cuadrante", "Política sugerida"]] + rows
    t = Table(data, colWidths=[3.2*cm, 20.5*cm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),PRIMARY), ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,0),10),
        ("FONTSIZE",(0,1),(-1,-1),9),
        ("ALIGN",(0,0),(-1,0),"LEFT"),
        ("GRID",(0,0),(-1,-1),0.25,colors.Color(0.85,0.87,0.90)),
        ("BACKGROUND",(0,1),(-1,-1),colors.whitesmoke),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))
    return t

# ─────────────────────────────────────────────────────────────
# Construcción del PDF
# ─────────────────────────────────────────────────────────────
class Footer(Flowable):
    def __init__(self, left, right, style): super().__init__(); self.left=left; self.right=right; self.style=style
    def draw(self):
        self.canv.saveState()
        self.canv.setFont(self.style.fontName, self.style.fontSize)
        self.canv.setFillColor(self.style.textColor)
        w, h = self.canv._pagesize
        self.canv.drawString(1.5*cm, 1.0*cm, self.left)
        self.canv.drawRightString(w-1.5*cm, 1.0*cm, self.right)
        self.canv.restoreState()

def make_table(df, col_formats=None, max_rows=25):
    df = df.head(max_rows).copy()
    if col_formats:
        for c,f in col_formats.items():
            if c in df.columns: df[c] = df[c].map(f)
    data = [list(df.columns)] + df.values.tolist()
    t = Table(data, hAlign="LEFT")
    style = [
        ("BACKGROUND",(0,0),(-1,0),PRIMARY), ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,0),9.5), ("FONTSIZE",(0,1),(-1,-1),8.5),
        ("GRID",(0,0),(-1,-1),0.25,colors.Color(0.85,0.87,0.90)),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]
    # zebra
    for r in range(1, len(data)):
        if r % 2 == 0:
            style.append(("BACKGROUND",(0,r),(-1,r),LIGHT))
    t.setStyle(TableStyle(style))
    return t

def build_pdf():
    st = build_styles()
    master, monthly, alerts = load_data()
    KPIs = compute_kpis(master, alerts)

    # Gráficos
    p_top  = chart_top_acv(master, 20)
    p_heat = chart_abcxyz_heat(master)

    # Documento
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(PDF_PATH), pagesize=landscape(A4),
        leftMargin=1.4*cm, rightMargin=1.4*cm, topMargin=1.2*cm, bottomMargin=1.5*cm,
        title="Reporte Mensual ABC–XYZ", author="Pipeline ABC–XYZ",
        subject="Clasificación y políticas de inventario"
    )
    story = []

    # Portada
    fecha = datetime.now().strftime("%d-%m-%Y")
    story += [Paragraph("Reporte Mensual ABC–XYZ", st["title"]), Spacer(1, 0.3*cm)]
    story += [Paragraph(f"Fecha de generación: <b>{fecha}</b>", st["h2"]),
              Paragraph("Fuente: SAP Business One (pipeline automatizado).", st["normal"]),
              Spacer(1, 0.4*cm)]
    if LOGO_PATH.exists(): story += [Image(str(LOGO_PATH), width=5.5*cm, height=1.8*cm), Spacer(1, 0.4*cm)]

    # Resumen ejecutivo (KPIs + impacto)
    kpi_tbl = Table([
        ["Ítems", fmt_int(KPIs["items"])],
        ["Alertas", fmt_int(KPIs["alerts"])],
        ["ACV total", fmt_money(KPIs["acv_tot"])],
        ["Clase A (SKUs)", f"{KPIs['pct_A_skus']:.1f}%"],
        ["Clase A (ACV)",  f"{KPIs['pct_A_acv']:.1f}%"],
        ["A×X (ACV)",      f"{KPIs['pct_AX_acv']:.1f}%"],
        ["Sugerido total",  fmt_money(KPIs.get("sugerido_total", 0))],
    ], colWidths=[5.0*cm, 5.0*cm])
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.whitesmoke),
        ("BOX",(0,0),(-1,-1),0.4,colors.Color(0.85,0.87,0.90)),
        ("INNERGRID",(0,0),(-1,-1),0.25,colors.Color(0.85,0.87,0.90)),
        ("FONTNAME",(0,0),(-1,-1),st["fontBase"]), ("FONTSIZE",(0,0),(-1,-1),10.5),
        ("TEXTCOLOR",(0,0),(0,-1),MUTED), ("TEXTCOLOR",(1,0),(1,-1),ACCENT),
        ("LEFTPADDING",(0,0),(-1,-1),8), ("RIGHTPADDING",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    story += [kpi_tbl, Spacer(1,0.5*cm)]

    # Beneficios / interpretación
    interp = build_interpretation(master, KPIs)
    bullets = ListFlowable(
        [ListItem(Paragraph(txt, st["normal"])) for txt in interp],
        bulletType='bullet', start='circle', leftPadding=12
    )
    story += [Paragraph("Interpretación y beneficios esperados", st["h1"]), Spacer(1,0.15*cm), bullets, Spacer(1,0.4*cm)]

    # Tabla de políticas por cuadrante
    story += [Paragraph("Políticas de inventario sugeridas por cuadrante", st["h1"]), Spacer(1,0.2*cm), policy_table(), PageBreak()]

    # Gráficos
    story += [Paragraph("Top-20 por ACV", st["h1"]), Spacer(1,0.2*cm), Image(str(p_top), width=24*cm, height=13*cm), Spacer(1,0.4*cm)]
    story += [Paragraph("Distribución ABC × XYZ", st["h1"]), Spacer(1,0.2*cm), Image(str(p_heat), width=16*cm, height=11*cm), PageBreak()]

    # Alertas TOP-30 con formateo
    story += [Paragraph("Alertas de reposición (TOP-30 por sugerido)", st["h1"]), Spacer(1,0.2*cm)]
    cols_alert = ["item_code","item_name","OnHand","ROP","EOQ","SMAX","SuggestedOrderQty"]
    alerts_view = (alerts[cols_alert].copy() if set(cols_alert).issubset(alerts.columns) else alerts.copy())
    if "SuggestedOrderQty" in alerts_view.columns:
        alerts_view = alerts_view.sort_values("SuggestedOrderQty", ascending=False)
    alert_tbl = make_table(alerts_view, {
        "OnHand": fmt_int, "ROP": fmt_int, "EOQ": fmt_int,
        "SMAX": fmt_int, "SuggestedOrderQty": fmt_int
    }, max_rows=30)
    story += [alert_tbl, PageBreak()]

    # Maestro TOP-50 por ACV
    story += [Paragraph("Maestro ABC–XYZ (TOP-50 por ACV)", st["h1"]), Spacer(1,0.2*cm)]
    cols_master = ["item_code","item_name","ABC","XYZ","annual_qty","unit_cost","ACV","ROP","SS","EOQ"]
    master_view = master[cols_master].copy() if set(cols_master).issubset(master.columns) else master.copy()
    master_view = master_view.sort_values("ACV", ascending=False)
    master_tbl = make_table(master_view, {
        "annual_qty": fmt_int, "unit_cost": fmt_money, "ACV": fmt_money,
        "ROP": fmt_int, "SS": fmt_int, "EOQ": fmt_int
    }, max_rows=50)
    story += [master_tbl]

    # Footer
    footL = f"Generado: {datetime.now().strftime('%d-%m-%Y %H:%M')}"
    footR = "Fuente: SAP B1 • ABC–XYZ"
    def _on_page(canvas, doc):
        Footer(footL, footR, st["smallR"]).wrapOn(canvas, *doc.pagesize)
        Footer(footL, footR, st["smallR"]).drawOn(canvas, 0, 0)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)

    # Limpieza temporal
    for p in CHARTS_DIR.glob("*.png"):
        try: p.unlink()
        except: pass

    print(f"PDF generado en {PDF_PATH}")

if __name__ == "__main__":
    build_pdf()
