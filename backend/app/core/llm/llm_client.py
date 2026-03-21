"""
LLM client facade.

This class keeps a stable API (`chat`, `chat_json`) while delegating provider-specific
differences to adapter implementations selected by factory.
"""

import json
import re
from typing import Any, Dict, List, Optional

from app.core.config import Config
from app.core.llm.factory import create_openai_provider, create_provider
from app.core.llm.types import LLMRequest, LLMResponse


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
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
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        operation: str = "llm.chat",
    ) -> str:
        response = self.generate(
            LLMRequest(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                metadata=metadata or {},
                operation=operation,
            )
        )
        return response.text

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        metadata: Optional[Dict[str, Any]] = None,
        operation: str = "llm.chat_json",
    ) -> Dict[str, Any]:
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            metadata=metadata,
            operation=operation,
        )

        cleaned_response = response.strip()
        cleaned_response = re.sub(r"^```(?:json)?\s*\n?", "", cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r"\n?```\s*$", "", cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON: {cleaned_response}") from exc

