"""
Copyright (c) 2026 Richard G and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from langfuse import Langfuse

from app.core.llm.providers.base import BaseLLMProvider
from app.core.llm.providers.openai.formatter import OpenAIMessageFormatter
from app.core.llm.providers.openai.normalizer import OpenAIResponseNormalizer
from app.core.llm.providers.openai.provider import OpenAIProvider
from app.core.utils.langfuse import get_langfuse_client


def create_openai_provider(
    model: str,
    api_key: str | None,
    base_url: str | None,
    langfuse: Langfuse | None = None,
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
    api_key: str | None,
    base_url: str | None,
    langfuse: Langfuse | None = None,
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
