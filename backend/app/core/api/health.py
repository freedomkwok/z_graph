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

from fastapi import APIRouter

from app.core.config import Config, settings

router = APIRouter()


@router.get("")
def health_check() -> dict[str, object]:
    zep_cloud_ready = bool(settings.zep_api_key)
    neo4j_ready = bool(settings.graphdb_uri and settings.graphdb_user and settings.graphdb_password)
    oracle_ready = bool(settings.graphdb_dsn and settings.graphdb_user and settings.graphdb_password)
    task_poll_interval_ms = int(getattr(settings, "task_poll_interval_ms", 2000) or 2000)
    if task_poll_interval_ms < 500:
        task_poll_interval_ms = 500
    graph_data_poll_interval_ms = int(
        getattr(settings, "graph_data_poll_interval_ms", 10000) or 10000
    )
    if graph_data_poll_interval_ms < 2000:
        graph_data_poll_interval_ms = 2000
    return {
        "status": "ok",
        "environment": settings.app_env,
        "zep_configured": bool(settings.zep_api_key),
        "zep_backend": str(settings.zep_backend or "").strip(),
        "task_poll_interval_ms": task_poll_interval_ms,
        "graph_data_poll_interval_ms": graph_data_poll_interval_ms,
        "graph_backend_options": {
            "zep_cloud": zep_cloud_ready,
            "neo4j": neo4j_ready,
            "oracle": oracle_ready,
        },
        "graphiti_embedding_model_options": Config.GRAPHITI_EMBEDDING_MODELS,
        "graphiti_default_embedding_model": Config.GRAPHITI_DEFAULT_EMBEDDING_MODEL,
        "graphiti_tracing_default_enabled": bool(Config.APPLY_LANGFUSE_TO_GRAPHITI_TRACE),
    }
