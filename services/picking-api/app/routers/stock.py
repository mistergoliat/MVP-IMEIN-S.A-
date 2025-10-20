from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..auth import get_current_user
from ..deps import get_session
from ..rbac import require_role

router = APIRouter()


@router.get("/products", response_model=list[schemas.ProductListItem])
async def list_products(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    q: str | None = Query(default=None, max_length=64),
    active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
):
    require_role(user, "operator")
    stmt = select(
        models.Product.item_code,
        models.Product.item_name,
        models.Product.uom,
        models.Product.active,
    )
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where((models.Product.item_code.ilike(term)) | (models.Product.item_name.ilike(term)))
    if active is not None:
        stmt = stmt.where(models.Product.active.is_(active))
    stmt = stmt.order_by(models.Product.item_name.asc()).limit(limit).offset(offset)
    rows = await session.execute(stmt)
    return [
        schemas.ProductListItem(item_code=code, item_name=name, uom=uom, active=active)
        for code, name, uom, active in rows.all()
    ]


@router.get("/products/export")
async def export_products_csv(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    q: str | None = Query(default=None, max_length=64),
    active: bool | None = None,
):
    require_role(user, "operator")
    stmt = select(
        models.Product.item_code,
        models.Product.item_name,
        models.Product.uom,
        models.Product.active,
    )
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where((models.Product.item_code.ilike(term)) | (models.Product.item_name.ilike(term)))
    if active is not None:
        stmt = stmt.where(models.Product.active.is_(active))
    stmt = stmt.order_by(models.Product.item_name.asc())
    rows = await session.execute(stmt)
    import csv, io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["item_code", "item_name", "uom", "active"])
    for code, name, uom, active in rows.all():
        writer.writerow([code, name, uom, active])
    from fastapi import Response
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=products.csv"},
    )


@router.post("/products", response_model=schemas.ProductListItem)
async def upsert_product(
    payload: schemas.ProductCreateUpdate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    require_role(user, "admin")
    code = payload.item_code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="item_code requerido")
    # case-insensitive lookup to avoid duplicates by case
    result = await session.execute(select(models.Product).where(func.lower(models.Product.item_code) == code.lower()))
    existing = result.scalar_one_or_none()
    if existing is None:
        prod = models.Product(
            item_code=code,
            item_name=payload.item_name.strip(),
            uom=payload.uom or "EA",
            requires_lot=bool(payload.requires_lot),
            requires_serial=bool(payload.requires_serial),
            active=bool(payload.active),
        )
        session.add(prod)
    else:
        existing.item_name = payload.item_name.strip() or existing.item_name
        existing.uom = payload.uom or existing.uom
        existing.requires_lot = bool(payload.requires_lot)
        existing.requires_serial = bool(payload.requires_serial)
        existing.active = bool(payload.active)
    await session.commit()
    row = await session.execute(select(models.Product.item_code, models.Product.item_name, models.Product.uom, models.Product.active).where(models.Product.item_code == code))
    code, name, uom, active = row.one()
    return schemas.ProductListItem(item_code=code, item_name=name, uom=uom, active=active)


@router.get("/products/{code}", response_model=schemas.ProductListItem)
async def get_product(
    code: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    require_role(user, "operator")
    result = await session.execute(select(models.Product).where(func.lower(models.Product.item_code) == code.strip().lower()))
    prod = result.scalar_one_or_none()
    if prod is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return schemas.ProductListItem(item_code=prod.item_code, item_name=prod.item_name, uom=prod.uom, active=prod.active)


@router.put("/products/{code}", response_model=schemas.ProductListItem)
async def update_product(
    code: str,
    payload: schemas.ProductCreateUpdate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    require_role(user, "admin")
    result = await session.execute(select(models.Product).where(func.lower(models.Product.item_code) == code.strip().lower()))
    prod = result.scalar_one_or_none()
    if prod is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    # Do not change primary key (item_code) to avoid FK issues
    prod.item_name = payload.item_name.strip() or prod.item_name
    prod.uom = payload.uom or prod.uom
    prod.requires_lot = bool(payload.requires_lot)
    prod.requires_serial = bool(payload.requires_serial)
    prod.active = bool(payload.active)
    await session.commit()
    return schemas.ProductListItem(item_code=prod.item_code, item_name=prod.item_name, uom=prod.uom, active=prod.active)


@router.delete("/products/{code}")
async def delete_product(
    code: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    require_role(user, "admin")
    code_norm = code.strip().lower()
    result = await session.execute(select(models.Product).where(func.lower(models.Product.item_code) == code_norm))
    prod = result.scalar_one_or_none()
    if prod is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    # Check references in stock and move_lines
    ref_stock = await session.execute(select(models.Stock).where(func.lower(models.Stock.item_code) == code_norm).limit(1))
    if ref_stock.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No se puede eliminar: el artículo tiene stock registrado")
    ref_move = await session.execute(select(models.MoveLine).where(func.lower(models.MoveLine.item_code) == code_norm).limit(1))
    if ref_move.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No se puede eliminar: el artículo está en movimientos")
    await session.delete(prod)
    await session.commit()
    return {"status": "deleted"}
