import re
from typing import Any

from app.core.llm.providers.abstractions import ResponseNormalizer
from app.core.llm.types import LLMResponse, LLMUsage


class OpenAIResponseNormalizer(ResponseNormalizer):
    def normalize(self, raw_response: Any, provider: str, model: str) -> LLMResponse:
        content = raw_response.choices[0].message.content or ""
        content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()

        usage = None
        if getattr(raw_response, "usage", None):
            usage = LLMUsage(
                prompt_tokens=raw_response.usage.prompt_tokens or 0,
                completion_tokens=raw_response.usage.completion_tokens or 0,
                total_tokens=raw_response.usage.total_tokens or 0,
            )

        raw = raw_response.model_dump() if hasattr(raw_response, "model_dump") else None
        return LLMResponse(
            text=content,
            provider=provider,
            model=model,
            finish_reason=raw_response.choices[0].finish_reason,
            usage=usage,
            raw=raw,
        )
