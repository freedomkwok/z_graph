import json
import logging
from typing import Any

import openai
from langfuse import Langfuse
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from app.core.llm.providers.abstractions import MessageFormatter, ResponseNormalizer
from app.core.llm.providers.base import BaseLLMProvider
from app.core.llm.providers.openai.formatter import OpenAIMessageFormatter
from app.core.llm.providers.openai.normalizer import OpenAIResponseNormalizer

logger = logging.getLogger("uvicorn.error")

MODELS_USING_MAX_COMPLETION_TOKENS_PREFIXES = (
    "gpt-5",
    "o1",
    "o3",
    "o4",
)



def model_uses_max_completion_tokens(model: str | None) -> bool:
    if not model:
        return False
    normalized = model.strip().lower()
    return normalized.startswith(MODELS_USING_MAX_COMPLETION_TOKENS_PREFIXES)


def sanitize_openai_chat_payload(payload: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    request_payload = {k: v for k, v in payload.items() if v is not None}
    resolved_model = str(request_payload.get("model") or model or "").strip()

    if model_uses_max_completion_tokens(resolved_model):
        max_tokens = request_payload.pop("max_tokens", None)
        if max_tokens is not None:
            request_payload["max_completion_tokens"] = max_tokens
    else:
        max_completion_tokens = request_payload.pop("max_completion_tokens", None)
        if max_completion_tokens is not None and "max_tokens" not in request_payload:
            request_payload["max_tokens"] = max_completion_tokens

    return request_payload


class OpenAIProvider(BaseLLMProvider):
    _MODELS_USING_MAX_COMPLETION_TOKENS_PREFIXES = MODELS_USING_MAX_COMPLETION_TOKENS_PREFIXES

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

    def _filter_config_params(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("OpenAI payload must be a dict")
        return sanitize_openai_chat_payload(payload, model=self.model)

    def _invoke(self, payload: Any) -> Any:
        request_payload = self._filter_config_params(payload)
        return self.client.chat.completions.create(**request_payload)


class GraphitiOpenAIGenericClient(OpenAIGenericClient):
    async def _generate_response(
        self,
        messages: list[Any],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = 16384,
        model_size: Any = None,
    ) -> dict[str, Any]:
        from graphiti_core.llm_client.errors import RateLimitError

        openai_messages: list[ChatCompletionMessageParam] = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == "user":
                openai_messages.append({"role": "user", "content": m.content})
            elif m.role == "system":
                openai_messages.append({"role": "system", "content": m.content})

        try:
            response_format: dict[str, Any] = {"type": "json_object"}
            if response_model is not None:
                schema_name = getattr(response_model, "__name__", "structured_response")
                json_schema = response_model.model_json_schema()
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": json_schema,
                    },
                }

            request_payload = sanitize_openai_chat_payload(
                {
                    "model": self.model,
                    "messages": openai_messages,
                    "temperature": self.temperature,
                    "max_tokens": max_tokens,
                    "response_format": response_format,
                },
                model=self.model,
            )
            response = await self.client.chat.completions.create(**request_payload)

            result = response.choices[0].message.content or ""
            return json.loads(result)
        except openai.RateLimitError as exc:
            raise RateLimitError from exc
        except Exception as exc:
            logger.error("Error in generating Graphiti LLM response: %s", exc)
            raise
