import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth as auth_utils
from .. import models, schemas
from ..deps import get_session

router = APIRouter()


async def _register_login_attempt(
    session: AsyncSession,
    *,
    username: str,
    success: bool,
    user_id: uuid.UUID | None,
    detail: str | None = None,
) -> None:
    session.add(
        models.Audit(
            entity="auth",
            entity_id=username,
            action="login_success" if success else "login_failed",
            payload_json={"username": username, "success": success, "detail": detail},
            user_id=user_id,
            ts=dt.datetime.utcnow(),
        )
    )
    await session.commit()


@router.post("/login", response_model=schemas.Token)
async def login(payload: schemas.LoginRequest, session: AsyncSession = Depends(get_session)) -> schemas.Token:
    result = await session.execute(select(models.User).where(models.User.username == payload.username))
    user = result.scalar_one_or_none()
    if user is None or not auth_utils.verify_password(payload.password, user.password_hash):
        await _register_login_attempt(
            session,
            username=payload.username,
            success=False,
            user_id=None,
            detail="Credenciales inválidas",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    if not user.active:
        await _register_login_attempt(
            session,
            username=payload.username,
            success=False,
            user_id=user.id,
            detail="Usuario inactivo",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")
    token = auth_utils.create_access_token({"sub": str(user.id), "role": user.role})
    await _register_login_attempt(
        session,
        username=payload.username,
        success=True,
        user_id=user.id,
    )
    return schemas.Token(access_token=token)


@router.post("/logout", status_code=204)
async def logout() -> None:  # pragma: no cover - placeholder
    return None
