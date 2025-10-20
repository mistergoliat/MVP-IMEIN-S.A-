from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..deps import get_session
from ..rbac import require_role
from .receipts import _enqueue_receipt_labels


router = APIRouter(prefix="/labels", tags=["labels"])


@router.post("/print/receipt/{gr_id}")
async def print_labels_for_receipt(
    gr_id: str, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)
):
    require_role(user, "operator")
    try:
        jobs = await _enqueue_receipt_labels(session, gr_id)
        await session.commit()
        return {"ok": True, "jobs": jobs, "message": "Etiquetas encoladas"}
    except Exception as e:  # pragma: no cover - simple surface
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Error imprimiendo: {e}")


@router.get("/queue")
async def list_print_queue(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    require_role(user, "operator")
    rows = await session.execute(
        text(
            """
            SELECT id, printer_name, copies, status, attempts, last_error, created_at
              FROM print_jobs
             ORDER BY created_at DESC
             LIMIT 100
            """
        )
    )
    return [dict(r._mapping) for r in rows]


@router.post("/retry")
async def retry_failed(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    require_role(user, "operator")
    await session.execute(text("UPDATE print_jobs SET status='queued' WHERE status='error'"))
    await session.commit()
    return {"ok": True, "message": "Reintentos encolados"}

