from abc import ABC, abstractmethod
from typing import Any, Dict

from app.core.llm.types import LLMRequest, LLMResponse


class MessageFormatter(ABC):
    @abstractmethod
    def format(self, request: LLMRequest, model: str) -> Dict[str, Any]:
        raise NotImplementedError


class ResponseNormalizer(ABC):
    @abstractmethod
    def normalize(self, raw_response: Any, provider: str, model: str) -> LLMResponse:
        raise NotImplementedError
