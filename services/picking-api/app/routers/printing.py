import datetime as dt
import os
import secrets
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas, zpl
from ..auth import get_current_user_optional
from ..deps import get_session
from ..rbac import require_role

router = APIRouter()

DEFAULT_PRINTER = os.getenv("PRINTER_NAME", "ZDesigner ZD888t")
SERVICE_TOKEN = os.getenv("PRINT_SERVICE_TOKEN")


def _service_actor() -> SimpleNamespace:
    return SimpleNamespace(role="admin")


async def _resolve_actor(request: Request, user=Depends(get_current_user_optional)):
    header_token = request.headers.get("X-Service-Token")
    if SERVICE_TOKEN and header_token and secrets.compare_digest(header_token, SERVICE_TOKEN):
        return user if user is not None else _service_actor()
    if user is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas")
    return user


@router.post("/product", response_model=schemas.PrintJobResponse)
async def enqueue_product_label(
    payload: schemas.PrintProductRequest,
    session: AsyncSession = Depends(get_session),
    actor=Depends(_resolve_actor),
) -> schemas.PrintJobResponse:
    require_role(actor, "operator")
    if payload.item_name is None:
        result = await session.execute(select(models.Product).where(models.Product.item_code == payload.item_code))
        product = result.scalar_one_or_none()
        if product is None:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        item_name = product.item_name
    else:
        item_name = payload.item_name

    fecha = payload.fecha_ingreso or dt.date.today()
    zpl_payload = zpl.render_product_label(
        item_code=payload.item_code,
        item_name=item_name,
        fecha_ingreso=fecha.strftime("%d-%m-%Y"),
    )
    job = models.PrintJob(
        printer_name=DEFAULT_PRINTER,
        payload_zpl=zpl_payload,
        copies=payload.copies,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return schemas.PrintJobResponse(
        id=job.id,
        printer_name=job.printer_name,
        status=job.status,
        copies=job.copies,
        payload_zpl=job.payload_zpl,
        attempts=job.attempts,
        last_error=job.last_error,
        created_at=job.created_at,
    )


@router.get("/jobs")
async def get_jobs(
    status: str = Query("queued"),
    limit: int = Query(25, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    actor=Depends(_resolve_actor),
):
    require_role(actor, "operator")
    result = await session.execute(
        select(models.PrintJob).where(models.PrintJob.status == status).order_by(models.PrintJob.created_at.asc()).limit(limit)
    )
    jobs = result.scalars().all()
    return [
        schemas.PrintJobResponse(
            id=j.id,
            printer_name=j.printer_name,
            status=j.status,
            copies=j.copies,
            payload_zpl=j.payload_zpl,
            attempts=j.attempts,
            last_error=j.last_error,
            created_at=j.created_at,
        )
        for j in jobs
    ]


@router.post("/jobs/{job_id}/ack")
async def ack_job(
    job_id: str,
    payload: schemas.PrintAckRequest,
    session: AsyncSession = Depends(get_session),
    actor=Depends(_resolve_actor),
):
    require_role(actor, "operator")
    result = await session.execute(select(models.PrintJob).where(models.PrintJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    job.status = payload.status
    job.last_error = payload.error
    job.attempts = job.attempts + 1 if payload.status in {"error", "retry"} else job.attempts
    job.updated_at = dt.datetime.utcnow()
    await session.commit()
    return {"status": job.status}
