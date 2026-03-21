"""
LLM client facade.

This class keeps a stable API while delegating provider-specific
differences to adapter implementations selected by factory.
"""

from typing import Any

from app.core.config import Config
from app.core.llm.factory import create_openai_provider, create_provider
from app.core.llm.types import LLMRequest, LLMResponse


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME
        raw_provider = provider or Config.LLM_PROVIDER or "openai"
        self.provider_name = raw_provider.strip().lower()

        if self.provider_name == "openai":
            self.provider = create_openai_provider(
                model=self.model,
                api_key=self.api_key,
                base_url=self.base_url,
            )
        else:
            self.provider = create_provider(
                provider_name=self.provider_name,
                model=self.model,
                api_key=self.api_key,
                base_url=self.base_url,
            )

    def generate(self, request: LLMRequest) -> LLMResponse:
        return self.provider.generate(request)

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        operation: str = "llm.chat",
    ) -> str:
        return self.provider.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            metadata=metadata,
            operation=operation,
        )

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        metadata: dict[str, Any] | None = None,
        operation: str = "llm.chat_json",
    ) -> dict[str, Any]:
        return self.provider.chat_json(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata=metadata,
            operation=operation,
        )
