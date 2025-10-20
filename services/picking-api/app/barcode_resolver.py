def resolve_barcode(barcode: str) -> tuple[str, str]:
    """MVP: treat barcode as item_code and item_name.
    Replace with lookup to item_master/barcode_map in future.
    """
    code = (barcode or "").strip()
    return code, code

