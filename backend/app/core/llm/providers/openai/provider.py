from typing import Any

from langfuse import Langfuse
from openai import OpenAI

from app.core.llm.providers.abstractions import MessageFormatter, ResponseNormalizer
from app.core.llm.providers.base import BaseLLMProvider
from app.core.llm.providers.openai.formatter import OpenAIMessageFormatter
from app.core.llm.providers.openai.normalizer import OpenAIResponseNormalizer


class OpenAIProvider(BaseLLMProvider):
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

    def _invoke(self, payload: Any) -> Any:
        return self.client.chat.completions.create(**payload)
