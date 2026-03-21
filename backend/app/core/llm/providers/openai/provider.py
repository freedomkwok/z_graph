from typing import Any, Optional

from openai import OpenAI

from app.core.llm.providers.abstractions import MessageFormatter, ResponseNormalizer
from app.core.llm.providers.base import BaseLLMProvider
from app.core.llm.providers.openai.formatter import OpenAIMessageFormatter
from app.core.llm.providers.openai.normalizer import OpenAIResponseNormalizer
from app.core.utils.langfuse import UnifiedLangfuseLogger


class OpenAIProvider(BaseLLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        logger: UnifiedLangfuseLogger,
        base_url: Optional[str] = None,
        formatter: Optional[MessageFormatter] = None,
        normalizer: Optional[ResponseNormalizer] = None,
        max_retries: int = 3,
        initial_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
        backoff_factor: float = 2.0,
    ) -> None:
        super().__init__(
            provider_name="openai",
            model=model,
            formatter=formatter or OpenAIMessageFormatter(),
            normalizer=normalizer or OpenAIResponseNormalizer(),
            logger=logger,
            max_retries=max_retries,
            initial_delay_seconds=initial_delay_seconds,
            max_delay_seconds=max_delay_seconds,
            backoff_factor=backoff_factor,
        )
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def _invoke(self, payload: Any) -> Any:
        return self.client.chat.completions.create(**payload)
