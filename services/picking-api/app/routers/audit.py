from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def list_audit() -> list[dict[str, str]]:  # pragma: no cover - placeholder
    return []
