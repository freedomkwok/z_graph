from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("")
def health_check() -> dict[str, object]:
    zep_cloud_ready = bool(settings.zep_api_key)
    neo4j_ready = bool(settings.graphdb_uri and settings.graphdb_user and settings.graphdb_password)
    oracle_ready = bool(settings.graphdb_dsn and settings.graphdb_user and settings.graphdb_password)
    return {
        "status": "ok",
        "environment": settings.app_env,
        "zep_configured": bool(settings.zep_api_key),
        "zep_backend": str(settings.zep_backend or "").strip(),
        "graph_backend_options": {
            "zep_cloud": zep_cloud_ready,
            "neo4j": neo4j_ready,
            "oracle": oracle_ready,
        },
    }
