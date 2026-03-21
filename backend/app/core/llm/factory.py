from typing import Optional

from app.core.config import Config
from app.core.llm.providers.base import BaseLLMProvider
from app.core.llm.providers.openai.formatter import OpenAIMessageFormatter
from app.core.llm.providers.openai.normalizer import OpenAIResponseNormalizer
from app.core.llm.providers.openai.provider import OpenAIProvider
from app.core.utils.langfuse import UnifiedLangfuseLogger


def create_openai_provider(
    model: str,
    api_key: Optional[str],
    base_url: Optional[str],
    logger: Optional[UnifiedLangfuseLogger] = None,
) -> BaseLLMProvider:
    if not api_key:
        raise ValueError("LLM_API_KEY is required for openai provider")

    langfuse_logger = logger or UnifiedLangfuseLogger()
    return OpenAIProvider(
        api_key=api_key,
        model=model,
        logger=langfuse_logger,
        base_url=base_url,
        formatter=OpenAIMessageFormatter(),
        normalizer=OpenAIResponseNormalizer(),
        max_retries=Config.LLM_MAX_RETRIES,
        initial_delay_seconds=Config.LLM_INITIAL_DELAY_SECONDS,
        max_delay_seconds=Config.LLM_MAX_DELAY_SECONDS,
        backoff_factor=Config.LLM_BACKOFF_FACTOR,
    )


def create_provider(
    provider_name: str,
    model: str,
    api_key: Optional[str],
    base_url: Optional[str],
) -> BaseLLMProvider:
    normalized = provider_name.strip().lower()
    if normalized == "openai":
        return create_openai_provider(
            model=model,
            api_key=api_key,
            base_url=base_url,
        )

    raise ValueError(f"Unsupported LLM provider: {provider_name}")
