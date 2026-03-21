from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("")
def health_check() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "environment": settings.app_env,
        "zep_configured": bool(settings.zep_api_key),
    }
