from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.application.router import router as application_router
from app.core.api.router import api_router
from app.core.config import settings

app = FastAPI(title=settings.app_name)
app.include_router(api_router, prefix=settings.api_prefix)
app.include_router(application_router, prefix=settings.api_prefix)

STATIC_DIR = Path(__file__).resolve().parent / "static"
ASSETS_DIR = STATIC_DIR / "assets"

if STATIC_DIR.exists():
    if ASSETS_DIR.exists():
        app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/")
    def root() -> dict[str, str]:
        return {"message": f"{settings.app_name} is running"}
