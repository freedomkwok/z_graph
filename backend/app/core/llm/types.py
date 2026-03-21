from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LLMRequest:
    messages: List[Dict[str, str]] = field(default_factory=list)
    system_message: Optional[str] = None
    user_message: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    response_format: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    operation: str = "llm.generate"

    def to_messages(self) -> List[Dict[str, str]]:
        if self.messages:
            return self.messages

        built_messages: List[Dict[str, str]] = []
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
    finish_reason: Optional[str] = None
    usage: Optional[LLMUsage] = None
    raw: Optional[Dict[str, Any]] = None
    latency_ms: Optional[float] = None
