import os
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..auth import get_current_user
from ..deps import get_session
from ..rbac import require_role

router = APIRouter()

ABCXYZ_FILE = "abcxyz_results.xlsx"


@router.get("/probe", response_model=schemas.ProbeResponse)
async def probe() -> schemas.ProbeResponse:
    directory = os.getenv("ABCXYZ_OUTPUT_DIR", "/data/abcxyz")
    file_path = Path(directory) / ABCXYZ_FILE
    return schemas.ProbeResponse(available=file_path.exists(), path=str(file_path))


@router.post("/from-local", response_model=schemas.ProductImportResult)
async def import_from_local(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> schemas.ProductImportResult:
    require_role(user, "supervisor")
    directory = os.getenv("ABCXYZ_OUTPUT_DIR", "/data/abcxyz")
    file_path = Path(directory) / ABCXYZ_FILE
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    df = pd.read_excel(file_path)
    df = df.fillna(0)
    count = 0
    for record in df.to_dict(orient="records"):
        payload = {k: record.get(k, 0) for k in (
            "item_code",
            "item_name",
            "monthly_mean",
            "monthly_std",
            "annual_qty",
            "ABC",
            "XYZ",
            "unit_cost",
            "ACV",
            "z_level",
            "lead_time_days",
            "SS",
            "ROP",
            "EOQ",
            "SMIN",
            "SMAX",
            "OnHand",
            "BelowROP",
        )}
        stmt = pg_insert(models.Product).values(**payload)
        update_cols = {c: stmt.excluded[c] for c in payload if c not in {"item_code"}}
        stmt = stmt.on_conflict_do_update(index_elements=[models.Product.item_code], set_=update_cols)
        await session.execute(stmt)
        count += 1
    await session.commit()
    return schemas.ProductImportResult(imported=count)
