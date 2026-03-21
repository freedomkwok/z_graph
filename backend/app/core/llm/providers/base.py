import json
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from time import perf_counter
from typing import Any

from langfuse import Langfuse
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Config
from app.core.llm.providers.abstractions import MessageFormatter, ResponseNormalizer
from app.core.llm.types import LLMRequest, LLMResponse


class BaseLLMProvider(ABC):
    def __init__(
        self,
        provider_name: str,
        model: str,
        formatter: MessageFormatter,
        normalizer: ResponseNormalizer,
        langfuse: Langfuse | None,
        max_retries: int = Config.LLM_MAX_RETRIES,
        initial_delay_seconds: float = Config.LLM_INITIAL_DELAY_SECONDS,
        max_delay_seconds: float = Config.LLM_MAX_DELAY_SECONDS,
        backoff_factor: float = Config.LLM_BACKOFF_FACTOR,
    ) -> None:
        self.provider_name = provider_name
        self.model = model
        self.formatter = formatter
        self.normalizer = normalizer
        self.langfuse = langfuse
        self.max_retries = max_retries
        self.initial_delay_seconds = initial_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.backoff_factor = backoff_factor

    def generate(self, request: LLMRequest) -> LLMResponse:
        started = perf_counter()
        payload = self.formatter.format(request=request, model=self.model)
        raw_response = self._run_with_retry(lambda: self._invoke(payload))
        response = self.normalizer.normalize(
            raw_response=raw_response,
            provider=self.provider_name,
            model=self.model,
        )
        response.latency_ms = (perf_counter() - started) * 1000
        return response

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
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
            ),
        )
        return response.text

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        metadata: dict[str, Any] | None = None,
        operation: str = "llm.chat_json",
    ) -> dict[str, Any]:
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

    def _run_with_retry(self, operation: Callable[[], Any]) -> Any:
        retrying = Retrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(
                multiplier=self.initial_delay_seconds,
                min=self.initial_delay_seconds,
                max=self.max_delay_seconds,
                exp_base=self.backoff_factor,
            ),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        return retrying(operation)

    @abstractmethod
    def _invoke(self, payload: Any) -> Any:
        raise NotImplementedError
