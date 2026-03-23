from fastapi import APIRouter

from app.core.api.health import router as health_router
from app.core.api.main import router as graph_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(graph_router, tags=["graph"])
