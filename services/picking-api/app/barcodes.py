class BarcodeError(Exception):
    """Errores relacionados con códigos de barra."""


def parse_hid_scan(scan: str) -> dict[str, str]:
    value = scan.strip()
    if "-" not in value:
        raise BarcodeError("Formato de documento inválido")
    prefix, number = value.split("-", 1)
    return {"doc_type": prefix, "doc_number": number}
