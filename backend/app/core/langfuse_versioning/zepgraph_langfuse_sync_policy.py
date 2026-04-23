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

Default Langfuse sync policy for the Zep Graph backend.

Other apps: subclass ``LangfuseSyncPolicy`` in ``llm_inference_core`` with your own categories,
source dirs, path allowlist, and pull-path layout. Then pass ``policy=`` to
``download_prompts_from_langfuse``, or in ``sync_to_langfuse.py`` assign ``POLICY`` after imports.
"""

from __future__ import annotations

import re
from pathlib import Path
from re import Pattern

from llm_inference_core.prompts.langfuse_sync_policy import LangfuseSyncPolicy

from app.core.langfuse_versioning.zepgraph_langfuse_sync_pull_layout import (
    build_pull_target_relative_path as zep_build_pull_target_relative_path,
)


def _compile_sync_path_allowlist() -> tuple[Pattern[str], ...]:
    return (
        re.compile(r"^ontology_section/prompts/[^/]+/(?:[^/]+/)?[^/]+\.(md|json)$"),
        re.compile(r"^ontology_section/labels/[^/]+/(?:[^/]+/)?[^/]+\.(md|json)$"),
        re.compile(r"^sub_queries/.+\.(md|json)$"),
        re.compile(r"^fallback_entities/.+\.(md|json)$"),
        re.compile(r"^auto_label_generator/prompts/[^/]+/.+\.(md|json)$"),
        re.compile(r"^auto_label_generator/labels/[^/]+/.+\.(md|json)$"),
    )


class ZepGraphLangfuseSyncPolicy(LangfuseSyncPolicy):
    """Paths and validation matching ``backend/app/core/langfuse_versioning``."""

    @property
    def supported_categories(self) -> frozenset[str]:
        return frozenset(
            {
                "ontology_section",
                "sub_queries",
                "fallback_entities",
                "auto_label_generator",
            }
        )

    @property
    def default_output_relative(self) -> str:
        return "app/core/langfuse_versioning"

    @property
    def default_source_directories(self) -> tuple[str, ...]:
        return (
            "app/core/langfuse_versioning/ontology_section",
            "app/core/langfuse_versioning/sub_queries",
            "app/core/langfuse_versioning/fallback_entities",
            "app/core/langfuse_versioning/auto_label_generator",
        )

    @property
    def langfuse_versioning_prefix(self) -> str:
        return "app/core/langfuse_versioning/"

    @property
    def sync_path_allowlist(self) -> tuple[Pattern[str], ...]:
        return _compile_sync_path_allowlist()

    @property
    def prompt_stem_aliases(self) -> dict[str, str]:
        return {
            "relations_in_system_prompt copy": "RELATIONS_IN_SYSTEM_PROMPT",
        }

    def build_pull_target_relative_path(self, prompt_name: str, label: str | None) -> Path:
        return zep_build_pull_target_relative_path(prompt_name, label, self)


DEFAULT_ZEPGRAPH_LANGFUSE_SYNC_POLICY = ZepGraphLangfuseSyncPolicy()
