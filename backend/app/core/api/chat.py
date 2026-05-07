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

from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()
_chat_sessions: set[str] = set()


class ChatMessageRequest(BaseModel):
    session_id: str = Field(min_length=1)
    query: str = Field(min_length=1)


@router.post("/session")
def create_chat_session() -> dict[str, object]:
    session_id = str(uuid4())
    _chat_sessions.add(session_id)
    return {"success": True, "session_id": session_id}


@router.post("/message")
def send_chat_message(request: ChatMessageRequest) -> dict[str, object]:
    session_id = request.session_id.strip()
    query = request.query.strip()
    if not session_id or session_id not in _chat_sessions:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")
    return {
        "success": True,
        "session_id": session_id,
        "reply": f"Chat backend received: {query}",
    }
