from fastapi import APIRouter

from app.core.api.health import router as health_router
from app.core.api.ontology import router as ontology_router
from app.core.api.project import router as project_router
from app.core.api.prompt_labels import router as prompt_label_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(ontology_router, tags=["ontology"])
api_router.include_router(prompt_label_router, tags=["prompt-label"])
api_router.include_router(project_router, tags=["graph"])
