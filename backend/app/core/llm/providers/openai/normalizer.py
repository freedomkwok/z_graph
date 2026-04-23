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

import re
from typing import Any

from app.core.llm.providers.abstractions import ResponseNormalizer
from app.core.llm.types import LLMResponse, LLMUsage


class OpenAIResponseNormalizer(ResponseNormalizer):
    def normalize(self, raw_response: Any, provider: str, model: str) -> LLMResponse:
        content = raw_response.choices[0].message.content or ""
        content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()

        usage = None
        if getattr(raw_response, "usage", None):
            usage = LLMUsage(
                prompt_tokens=raw_response.usage.prompt_tokens or 0,
                completion_tokens=raw_response.usage.completion_tokens or 0,
                total_tokens=raw_response.usage.total_tokens or 0,
            )

        raw = raw_response.model_dump() if hasattr(raw_response, "model_dump") else None
        return LLMResponse(
            text=content,
            provider=provider,
            model=model,
            finish_reason=raw_response.choices[0].finish_reason,
            usage=usage,
            raw=raw,
        )
