from __future__ import annotations

import socket
import time

from .zpl_renderer import render_label
from ..core.config import settings


def select_template(copies: int) -> str:
    layout = settings.PRINTER_LAYOUT
    if layout == "2across":
        if copies == 1 and settings.PRINTER_DUPLICATE_SINGLE:
            return "etiqueta_50x30_2across_duplicada"
        return "etiqueta_50x30_2across"
    return settings.LABEL_TEMPLATE or "etiqueta_50x30"


def send_raw_zpl(
    zpl: bytes,
    host: str,
    port: int = 9100,
    attempts: int = 3,
    timeout: float = 3.0,
) -> bool:
    last_error: str | None = None
    for attempt in range(attempts):
        try:
            with socket.create_connection((host, port), timeout=timeout) as conn:
                conn.sendall(zpl)
            return True
        except Exception as exc:  # pragma: no cover - network failures depend on environment
            last_error = str(exc)
            time.sleep(2**attempt)
    raise RuntimeError(last_error or "Unknown printer error")
