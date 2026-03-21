from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any, Callable

from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.llm.providers.abstractions import MessageFormatter, ResponseNormalizer
from app.core.llm.types import LLMRequest, LLMResponse
from app.core.utils.langfuse import UnifiedLangfuseLogger


class BaseLLMProvider(ABC):
    def __init__(
        self,
        provider_name: str,
        model: str,
        formatter: MessageFormatter,
        normalizer: ResponseNormalizer,
        logger: UnifiedLangfuseLogger,
        max_retries: int = 3,
        initial_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
        backoff_factor: float = 2.0,
    ) -> None:
        self.provider_name = provider_name
        self.model = model
        self.formatter = formatter
        self.normalizer = normalizer
        self.logger = logger
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

        self.logger.log_generation(
            operation=request.operation,
            provider=response.provider,
            model=response.model,
            messages=request.to_messages(),
            output_text=response.text,
            usage=response.usage,
            metadata=request.metadata,
            latency_ms=response.latency_ms,
        )
        return response

    def _run_with_retry(self, fn: Callable[[], Any]) -> Any:
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
        return retrying(fn)

    @abstractmethod
    def _invoke(self, payload: Any) -> Any:
        raise NotImplementedError
