from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..core.config import settings
from ..deps import get_session
from ..services import zpl_print

router = APIRouter(prefix="/labels", tags=["labels"])


@router.get("/config")
def label_config():
    return {
        "mode": settings.PRINTER_MODE,
        "layout": settings.PRINTER_LAYOUT,
        "duplicate_single": settings.PRINTER_DUPLICATE_SINGLE,
        "host": settings.PRINTER_HOST,
        "port": settings.PRINTER_PORT,
    }


class LabelPayload(BaseModel):
    item_code: str
    item_name: str | None = None
    fecha: str | None = None
    copies: int = Field(ge=1, le=10, default=1)


def _clean_code(value: str) -> str:
    return (value or "").strip().upper()


def _normalized_fecha(value: str | None) -> str:
    if value:
        value = value.strip()
        if value:
            return value
    return datetime.now().strftime("%d-%m-%Y")


async def _get_product(session: AsyncSession, item_code: str) -> models.Product:
    code = _clean_code(item_code)
    if not code:
        raise HTTPException(status_code=400, detail="Ingresa un codigo de producto.")
    stmt = select(models.Product).where(models.Product.item_code == code)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="El codigo no existe en el catalogo.")
    return product


def _physical_labels(template: str, requested: int) -> int:
    if template == "etiqueta_50x30_2across_duplicada":
        return requested * 2
    if template == "etiqueta_50x30_2across":
        pairs = (requested + 1) // 2
        return pairs * 2
    return requested


@router.get("/products")
async def search_products(
    q: str = Query(..., min_length=1, max_length=64),
    field: str = Query("name"),
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    field_norm = field.lower()
    if field_norm not in {"name", "code"}:
        raise HTTPException(status_code=400, detail="Parametro 'field' invalido.")
    term = q.strip()
    if not term:
        return []
    stmt = select(models.Product.item_code, models.Product.item_name).where(models.Product.active.is_(True))
    pattern = f"%{term}%"
    if field_norm == "code":
        pattern = f"{_clean_code(term)}%"
        stmt = stmt.where(models.Product.item_code.ilike(pattern))
    else:
        stmt = stmt.where(models.Product.item_name.ilike(pattern))
    stmt = stmt.order_by(models.Product.item_name.asc()).limit(limit)
    rows = await session.execute(stmt)
    return [
        {"item_code": item_code, "item_name": item_name}
        for item_code, item_name in rows.all()
    ]


@router.post("/preview")
async def preview_label(payload: LabelPayload, session: AsyncSession = Depends(get_session)):
    # Try to fetch product; if missing and item_name provided, proceed with provided data
    body: dict[str, Any] = payload.model_dump()
    try:
        product = await _get_product(session, payload.item_code)
        body["item_code"] = product.item_code
        body["item_name"] = product.item_name
    except HTTPException as exc:
        if exc.status_code == 404 and payload.item_name:
            body["item_code"] = _clean_code(payload.item_code)
            body["item_name"] = str(payload.item_name).strip()
        else:
            raise
    body["fecha"] = _normalized_fecha(body.get("fecha"))
    body["copies"] = payload.copies

    tpl = zpl_print.select_template(payload.copies)
    zpl = zpl_print.render_label(tpl, body)
    effective = _physical_labels(tpl, payload.copies)
    return {
        "template": tpl,
        "copies": payload.copies,
        "effective_labels": effective,
        "mode": settings.PRINTER_MODE,
        "zpl": zpl,
        "item_code": product.item_code,
        "item_name": product.item_name,
        "fecha": body["fecha"],
    }


@router.post("/print")
async def print_label(payload: LabelPayload, session: AsyncSession = Depends(get_session)):
    # Same fallback policy as preview
    body: dict[str, Any] = payload.model_dump()
    try:
        product = await _get_product(session, payload.item_code)
        body["item_code"] = product.item_code
        body["item_name"] = product.item_name
    except HTTPException as exc:
        if exc.status_code == 404 and payload.item_name:
            body["item_code"] = _clean_code(payload.item_code)
            body["item_name"] = str(payload.item_name).strip()
        else:
            raise
    body["fecha"] = _normalized_fecha(body.get("fecha"))
    body["copies"] = payload.copies

    tpl = zpl_print.select_template(payload.copies)
    zpl = zpl_print.render_label(tpl, body)

    if settings.PRINTER_MODE == "network":
        zpl_print.send_raw_zpl(zpl.encode("utf-8"), settings.PRINTER_HOST, settings.PRINTER_PORT)

    effective = _physical_labels(tpl, payload.copies)
    response = {
        "template": tpl,
        "copies": payload.copies,
        "effective_labels": effective,
        "status": "queued" if settings.PRINTER_MODE == "network" else "rendered",
        "mode": settings.PRINTER_MODE,
        "item_code": product.item_code,
        "item_name": product.item_name,
        "fecha": body["fecha"],
    }
    if settings.PRINTER_MODE == "local":
        response["zpl"] = zpl
    return response
