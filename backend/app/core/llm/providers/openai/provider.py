from typing import Any

from langfuse import Langfuse
from openai import OpenAI

from app.core.llm.providers.abstractions import MessageFormatter, ResponseNormalizer
from app.core.llm.providers.base import BaseLLMProvider
from app.core.llm.providers.openai.formatter import OpenAIMessageFormatter
from app.core.llm.providers.openai.normalizer import OpenAIResponseNormalizer


class OpenAIProvider(BaseLLMProvider):
    _MODELS_USING_MAX_COMPLETION_TOKENS_PREFIXES = (
        "gpt-5",
        "o1",
        "o3",
        "o4",
    )

    def __init__(
        self,
        api_key: str,
        model: str,
        langfuse: Langfuse | None,
        base_url: str | None = None,
        formatter: MessageFormatter | None = None,
        normalizer: ResponseNormalizer | None = None,
    ) -> None:
        super().__init__(
            provider_name="openai",
            model=model,
            formatter=formatter or OpenAIMessageFormatter(),
            normalizer=normalizer or OpenAIResponseNormalizer(),
            langfuse=langfuse,
        )
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self._uses_max_completion_tokens = self._model_uses_max_completion_tokens(
            str(model or "").strip().lower()
        )

    def _normalize_token_budget_param(self, payload: Any) -> dict[str, Any]:
        request_payload = dict(payload or {})
        if self._uses_max_completion_tokens:
            max_tokens = request_payload.pop("max_tokens", None)
            if max_tokens is not None and "max_completion_tokens" not in request_payload:
                request_payload["max_completion_tokens"] = max_tokens
        else:
            max_completion_tokens = request_payload.pop("max_completion_tokens", None)
            if max_completion_tokens is not None and "max_tokens" not in request_payload:
                request_payload["max_tokens"] = max_completion_tokens
        return request_payload

    @classmethod
    def _model_uses_max_completion_tokens(cls, model_name: str) -> bool:
        return any(
            model_name.startswith(prefix)
            for prefix in cls._MODELS_USING_MAX_COMPLETION_TOKENS_PREFIXES
        )

    def _invoke(self, payload: Any) -> Any:
        request_payload = self._normalize_token_budget_param(payload)
        return self.client.chat.completions.create(**request_payload)
