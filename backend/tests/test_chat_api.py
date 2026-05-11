from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.api import chat
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
    agent_calls: list[dict[str, object]] = []

    class FakeAgentResponse:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "task_id": "task-1",
                "task_status": "completed",
                "final_text": "Graph answer",
            }

    class FakeAgentClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "FakeAgentClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, json: dict[str, object]) -> FakeAgentResponse:
            agent_calls.append({"url": url, "json": json, "timeout": self.timeout})
            return FakeAgentResponse()

    app = FastAPI()
    app.include_router(router, prefix="/api/chat")
    client = TestClient(app)
    session_id = client.post("/api/chat/session").json()["session_id"]
    previous_base_url = chat.settings.agent_api_base_url
    chat.settings.agent_api_base_url = "http://agent-api.test"

    try:
        original_client = chat.httpx.Client
        chat.httpx.Client = FakeAgentClient
        response = client.post(
            "/api/chat/message",
            json={
                "session_id": session_id,
                "query": "What is in this graph?",
                "graph_id": "graph-1",
                "project_id": "project-1",
            },
        )
    finally:
        chat.httpx.Client = original_client
        chat.settings.agent_api_base_url = previous_base_url

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "success": True,
        "session_id": session_id,
        "reply": "Graph answer",
        "task_id": "task-1",
        "task_status": "completed",
    }
    assert agent_calls == [
        {
            "url": "http://agent-api.test/chat",
            "json": {
                "message": "What is in this graph?",
                "graph_id": "graph-1",
                "metadata": {"project_id": "project-1"},
            },
            "timeout": chat.settings.agent_api_timeout_seconds,
        }
    ]


def test_chat_message_requires_graph_id() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/chat")
    client = TestClient(app)
    session_id = client.post("/api/chat/session").json()["session_id"]

    response = client.post(
        "/api/chat/message",
        json={"session_id": session_id, "query": "What is in this graph?"},
    )

    assert response.status_code == 422
