from typing import Any

from app.core.llm.providers.abstractions import MessageFormatter
from app.core.llm.types import LLMRequest


class OpenAIMessageFormatter(MessageFormatter):
    def format(self, request: LLMRequest, model: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": request.to_messages(),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.response_format:
            payload["response_format"] = request.response_format
        return payload
