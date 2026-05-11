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

from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter()
_chat_sessions: set[str] = set()


class ChatMessageRequest(BaseModel):
    session_id: str = Field(min_length=1)
    graph_id: str = Field(min_length=1)
    query: str | None = None
    message: str | None = None
    project_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _agent_chat_url() -> str:
    return f"{settings.agent_api_base_url.rstrip('/')}/chat"


def _agent_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or "Agent chat request failed"
    if isinstance(payload, dict):
        return str(payload.get("detail") or payload.get("error") or "Agent chat request failed")
    return "Agent chat request failed"


@router.post("/session")
def create_chat_session() -> dict[str, object]:
    session_id = str(uuid4())
    _chat_sessions.add(session_id)
    return {"success": True, "session_id": session_id}


@router.post("/message")
def send_chat_message(request: ChatMessageRequest) -> dict[str, object]:
    session_id = request.session_id.strip()
    query = str(request.query or request.message or "").strip()
    graph_id = request.graph_id.strip()
    if not session_id or session_id not in _chat_sessions:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")
    if not graph_id:
        raise HTTPException(status_code=400, detail="Graph id is required")

    metadata = dict(request.metadata)
    project_id = str(request.project_id or "").strip()
    if project_id:
        metadata["project_id"] = project_id

    agent_request = {
        "message": query,
        "graph_id": graph_id,
        "metadata": metadata,
    }

    try:
        with httpx.Client(timeout=settings.agent_api_timeout_seconds) as client:
            response = client.post(_agent_chat_url(), json=agent_request)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Agent chat request failed: {exc}") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=_agent_error_detail(response))

    agent_payload = response.json()
    return {
        "success": True,
        "session_id": session_id,
        "reply": str(agent_payload.get("final_text") or ""),
        "task_id": agent_payload.get("task_id"),
        "task_status": agent_payload.get("task_status"),
    }
