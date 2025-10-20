from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
import unicodedata

TPL_DIR = Path(__file__).resolve().parents[1] / "templates" / "zpl"

env = Environment(
    loader=FileSystemLoader(TPL_DIR),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _norm(value: str | None, max_len: int | None = None) -> str:
    text = "" if value is None else value
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.strip().upper()
    if max_len:
        return text[:max_len]
    return text


def _base_label(ctx: dict[str, Any]) -> dict[str, str]:
    return {
        "item_code": _norm(ctx.get("item_code"), 24),
        "item_name": _norm(ctx.get("item_name"), 32),
        "fecha": _norm(ctx.get("fecha"), 16),
    }


def _render_pairs(label: dict[str, str], copies: int) -> str:
    template = env.get_template("etiqueta_50x30_2across.zpl.j2")
    pairs: list[dict[str, dict[str, str] | None]] = []
    remaining = copies
    while remaining > 0:
        left = deepcopy(label)
        if remaining >= 2:
            right: dict[str, str] | None = deepcopy(label)
            remaining -= 2
        else:
            # Duplicate the last label to avoid leaving an empty column.
            right = deepcopy(label)
            remaining -= 1
        pairs.append({"left": left, "right": right})
    return template.render(pairs=pairs)


def render_label(tpl: str, ctx: dict[str, Any]) -> str:
    label = _base_label(ctx)
    copies = int(ctx.get("copies", 1) or 1)

    if tpl == "etiqueta_50x30_2across":
        return _render_pairs(label, copies)

    template = env.get_template(f"{tpl}.zpl.j2")
    data = {
        **label,
        "copies": copies,
        "col": ctx.get("col", "L"),
    }
    return template.render(**data)
