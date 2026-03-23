from typing import Optional

from app.core.llm.providers.base import BaseLLMProvider
from app.core.llm.providers.openai.formatter import OpenAIMessageFormatter
from app.core.llm.providers.openai.normalizer import OpenAIResponseNormalizer
from app.core.llm.providers.openai.provider import OpenAIProvider
from app.core.utils.langfuse import get_langfuse_client
from langfuse import Langfuse


def create_openai_provider(
    model: str,
    api_key: Optional[str],
    base_url: Optional[str],
    langfuse: Optional[Langfuse] = None,
) -> OpenAIProvider:
    if not api_key:
        raise ValueError("LLM_API_KEY is required for openai provider")
    resolved_langfuse = langfuse or get_langfuse_client()

    return OpenAIProvider(
        api_key=api_key,
        model=model,
        langfuse=resolved_langfuse,
        base_url=base_url,
        formatter=OpenAIMessageFormatter(),
        normalizer=OpenAIResponseNormalizer(),
    )


def create_provider(
    provider_name: str,
    model: str,
    api_key: Optional[str],
    base_url: Optional[str],
    langfuse: Optional[Langfuse] = None,
) -> BaseLLMProvider:
    normalized = provider_name.strip().lower()
    if normalized == "openai":
        return create_openai_provider(
            model=model,
            api_key=api_key,
            base_url=base_url,
            langfuse=langfuse,
        )

    raise ValueError(f"Unsupported LLM provider: {provider_name}")
