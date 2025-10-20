from fastapi import HTTPException, status

from .models import User

ROLE_HIERARCHY = {
    "operator": 0,
    "supervisor": 1,
    "admin": 2,
}


def require_role(user: User, role: str) -> None:
    required = ROLE_HIERARCHY.get(role)
    current = ROLE_HIERARCHY.get(user.role)
    if required is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol requerido inválido")
    if current is None or current < required:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
