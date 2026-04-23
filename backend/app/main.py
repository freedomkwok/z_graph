"""
Copyright (c) 2026 Richard G and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.application.router import router as application_router
from app.core.api.router import api_router
from app.core.config import settings
from app.core.managers.prompt_label_manager import PromptLabelManager
from app.core.managers.project_manager import ProjectManager

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


def _configure_graphiti_core_logging() -> None:
    """Route graphiti_core logs to stderr when GRAPHITI_LOG_LEVEL is set.

    Uvicorn's default dictConfig wires handlers only for ``uvicorn*`` loggers.
    Library modules use ``logging.getLogger(__name__)`` under ``graphiti_core``;
    those records inherit the root effective level (WARNING) and never print
    ``logger.info`` lines unless this (or a custom logging dict) enables them.
    """
    lib = logging.getLogger("graphiti_core")
    if getattr(lib, "_z_graph_logging_configured", False):
        return
    raw = (os.getenv("GRAPHITI_LOG_LEVEL") or "").strip().upper()
    if not raw:
        return
    level = getattr(logging, raw, None)
    if level is None or not isinstance(level, int):
        return
    lib.setLevel(level)
    if not lib.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        lib.addHandler(handler)
    lib.propagate = False
    setattr(lib, "_z_graph_logging_configured", True)


@app.on_event("startup")
def initialize_project_storage() -> None:
    _configure_graphiti_core_logging()
    ProjectManager.initialize_storage()
    PromptLabelManager.initialize_labels()
