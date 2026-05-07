from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.api.chat import router


def test_create_chat_session_returns_session_id() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/chat")
    client = TestClient(app)

    response = client.post("/api/chat/session")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert isinstance(payload["session_id"], str)
    assert payload["session_id"]


def test_chat_message_returns_reply_for_session() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/chat")
    client = TestClient(app)
    session_id = client.post("/api/chat/session").json()["session_id"]

    response = client.post(
        "/api/chat/message",
        json={"session_id": session_id, "query": "What is in this graph?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "success": True,
        "session_id": session_id,
        "reply": "Chat backend received: What is in this graph?",
    }
