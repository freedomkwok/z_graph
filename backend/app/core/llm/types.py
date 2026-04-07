from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMRequest:
    messages: list[dict[str, str]] = field(default_factory=list)
    system_message: str | None = None
    user_message: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    response_format: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    operation: str = "llm.generate"

    def to_messages(self) -> list[dict[str, str]]:
        if self.messages:
            return self.messages

        built_messages: list[dict[str, str]] = []
        if self.system_message:
            built_messages.append({"role": "system", "content": self.system_message})
        if self.user_message:
            built_messages.append({"role": "user", "content": self.user_message})

        if not built_messages:
            raise ValueError("LLMRequest requires messages or user_message")
        return built_messages


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    finish_reason: str | None = None
    usage: LLMUsage | None = None
    raw: dict[str, Any] | None = None
    latency_ms: float | None = None
