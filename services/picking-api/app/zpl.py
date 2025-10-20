from jinja2 import Template

ZPL_TEMPLATE = Template(
    """^XA
^CI28
^PW240
^LL400
^FO10,10^A0N,26,26^FD{{ item_name }}^FS
^FO10,50^A0N,24,24^FDSKU: {{ item_code }}^FS
^FO10,90^BCN,80,Y,N,N^FD{{ item_code }}^FS
^FO10,190^A0N,22,22^FDFECHA: {{ fecha_ingreso }}^FS
^XZ"""
)


def render_product_label(item_code: str, item_name: str, fecha_ingreso: str) -> str:
    return ZPL_TEMPLATE.render(
        item_code=item_code,
        item_name=item_name,
        fecha_ingreso=fecha_ingreso,
    )


def build_zpl_label(
    item_code: str,
    item_name: str,
    qty: float,
    uom: str,
    warehouse: str,
    batch: str | None = None,
    serial: str | None = None,
) -> str:
    """Genera etiqueta estándar ZD888T (simple, sin fuentes extendidas)."""
    safe_name = (item_name or "")[:30]
    safe_batch = batch or "-"
    safe_serial = serial or "-"
    # Keep ASCII to avoid codepage issues on ZD888t unless custom fonts loaded
    return (
        f"^XA\n"
        f"^CF0,40\n"
        f"^FO30,30^FD{safe_name}^FS\n"
        f"^CF0,30\n"
        f"^FO30,80^FDCode: {item_code}^FS\n"
        f"^FO30,120^FDQty: {qty:g} {uom}^FS\n"
        f"^FO30,160^FDWH: {warehouse}^FS\n"
        f"^FO30,200^FDBatch: {safe_batch}^FS\n"
        f"^FO30,240^FDSerial: {safe_serial}^FS\n"
        f"^BY2,2,50\n"
        f"^FO30,290^BCN,80,Y,N,N\n"
        f"^FD{item_code}^FS\n"
        f"^XZ"
    )
