"""
Ontology generation service.
API 1: analyze text and emit entity/relation type definitions.
"""

import json
import re
from pathlib import Path
from typing import Any

from app.core.config import Config
from app.core.langfuse_versioning.prompt_provider import PromptProvider, make_prompt_provider
from app.core.llm.factory import create_openai_provider
from app.core.llm.providers.openai.provider import OpenAIProvider


class OntologyGenerator:
    """
    Builds ontology definitions from documents and contextual requirements.
    """

    DEFAULT_PROMPT_LABEL = "Production"
    USER_EXTRACTION_PROMPT_NAME = "prompts/USER_EXTRACTION_PROMPT.md"
    ONTOLOGY_SYSTEM_PROMPT_NAME = "prompts/ONTOLOGY_SYSTEM_PROMPT.md"
    PERSON_FALLBACK_NAME = "fallback_entities/person.json"
    ORGANIZATION_FALLBACK_NAME = "fallback_entities/organization.json"
    _PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

    def __init__(
        self,
        llm_provider: OpenAIProvider | None = None,
        prompt_provider: PromptProvider | None = None,
        fallback_entity_provider: PromptProvider | None = None,
    ):
        self.llm = llm_provider or create_openai_provider(
            model=Config.LLM_MODEL_NAME,
            api_key=Config.LLM_API_KEY,
            base_url=Config.LLM_BASE_URL,
        )
        base_dir = Path(__file__).resolve().parent.parent / "langfuse_versioning"
        # Unified root so keys like prompts/* and fallback_entities/* resolve identically
        # for both Langfuse and local file fallback.
        self.prompt_provider = prompt_provider or make_prompt_provider(prompts_dir=base_dir)
        self.fallback_entity_provider = fallback_entity_provider or make_prompt_provider(
            prompts_dir=base_dir
        )

    def generate(
        self,
        document_texts: list[str],
        context_requirement: str = "",
        additional_context: str | None = None,
        prompt_label: str | None = None,
    ) -> dict[str, Any]:
        effective_prompt_label = self._normalize_prompt_label(prompt_label)
        # Build user message
        user_message = self._build_user_message(
            document_texts,
            context_requirement,
            additional_context,
            prompt_label=effective_prompt_label,
        )

        messages = [
            {"role": "system", "content": self._get_system_prompt(prompt_label=effective_prompt_label)},
            {"role": "user", "content": user_message},
        ]

        result = self.llm.chat_json(messages=messages, temperature=0.3, max_tokens=12096)
        result = self._faillback_process(result, prompt_label=effective_prompt_label)

        return result

    # Max characters sent to the LLM (~50k Chinese chars)
    MAX_TEXT_LENGTH_FOR_LLM = 50000

    def _build_user_message(
        self,
        document_texts: list[str],
        context_requirement: str,
        additional_context: str | None,
        prompt_label: str,
    ) -> str:
        """Assemble the user message payload."""

        # Merge documents
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)

        # Truncate if over limit (LLM input only; graph build uses full text elsewhere)
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[: self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += (
                f"\n\n...(Total length: {original_length} chars; "
                f"only first {self.MAX_TEXT_LENGTH_FOR_LLM} chars included for ontology analysis)..."
            )

        return self.prompt_provider.get(
            self.USER_EXTRACTION_PROMPT_NAME,
            label=prompt_label,
            context_requirement=context_requirement or "Not provided",
            combined_text=combined_text,
            additional_context=additional_context or "Not provided",
        )

    def _get_system_prompt(self, prompt_label: str) -> str:
        template = self.prompt_provider.get(
            self.ONTOLOGY_SYSTEM_PROMPT_NAME,
            label=prompt_label,
        )
        placeholder_vars = self._build_system_prompt_placeholder_vars(template, prompt_label=prompt_label)
        # Single source of truth: render the already-loaded template in-memory.
        return self._render_dynamic_placeholders(template or "", placeholder_vars).strip()

    def _build_system_prompt_placeholder_vars(
        self, template: str, *, prompt_label: str
    ) -> dict[str, str]:
        placeholder_vars: dict[str, str] = {}
        for key in self._extract_placeholder_keys(template):
            normalized_key = self._normalize_placeholder_key(key)
            value = self._load_system_prompt_fragment(normalized_key, prompt_label=prompt_label)
            if value:
                # Keep original template key so replacement always matches source template.
                placeholder_vars[key] = value
        return placeholder_vars

    def _extract_placeholder_keys(self, template: str) -> list[str]:
        seen = set[Any]()
        ordered: list[str] = []
        for match in self._PLACEHOLDER_PATTERN.finditer(template):
            key = match.group(1)
            if key not in seen:
                seen.add(key)
                ordered.append(key)
        return ordered

    def _render_dynamic_placeholders(self, template: str, placeholder_vars: dict[str, str]) -> str:
        def replacer(match: re.Match[str]) -> str:
            key = match.group(1)
            return placeholder_vars.get(key, match.group(0))

        return self._PLACEHOLDER_PATTERN.sub(replacer, template)

    @staticmethod
    def _normalize_placeholder_key(placeholder_key: str) -> str:
        normalized = placeholder_key
        if "ORGANIZATIONS_" in normalized:
            normalized = normalized.replace("ORGANIZATIONS_", "ORGANIZATION_", 1)
        if "ENTITIES_" in normalized:
            normalized = normalized.replace("ENTITIES_", "ENTITES_", 1)
        return normalized

    def _load_system_prompt_fragment(self, placeholder_key: str, *, prompt_label: str) -> str:
        prompt_name = f"prompts/{placeholder_key}.md"
        try:
            fragment = self.prompt_provider.get(prompt_name, label=prompt_label)
            fragment = (fragment or "").strip()
            if fragment:
                return fragment
        except Exception:
            return ""
        return ""

    def _faillback_process(self, result: dict[str, Any], *, prompt_label: str) -> dict[str, Any]:
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""

        for entity in result["entity_types"]:
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # Cap description length
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."

        for edge in result["edge_types"]:
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."

        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10

        person_fallback = self._load_fallback_entity(self.PERSON_FALLBACK_NAME, prompt_label=prompt_label)
        organization_fallback = self._load_fallback_entity(
            self.ORGANIZATION_FALLBACK_NAME, prompt_label=prompt_label
        )

        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names

        # Fallbacks to append
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)

        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)

            # Drop tail types if we would exceed the cap
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                # Remove from the end (keep earlier specific types)
                result["entity_types"] = result["entity_types"][:-to_remove]

            result["entity_types"].extend(fallbacks_to_add)

        # Hard cap (defensive)
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]

        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]

        return result

    def _load_fallback_entity(self, file_name: str, *, prompt_label: str) -> dict[str, Any]:
        """
        Resolve fallback entity definition:
        1) Prompt provider with label=Production (remote first)
        2) Local JSON via provider fallback
        """
        try:
            raw = self.fallback_entity_provider.get(file_name, label=prompt_label)
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("name"):
                payload.setdefault("attributes", [])
                payload.setdefault("examples", [])
                return payload
        except Exception as exc:
            raise ValueError(
                f"Failed loading fallback entity definition '{file_name}' from provider/file fallback"
            ) from exc

        raise ValueError(f"Invalid fallback entity definition format for '{file_name}'")

    @classmethod
    def _normalize_prompt_label(cls, prompt_label: str | None) -> str:
        normalized = str(prompt_label or "").strip()
        return normalized or cls.DEFAULT_PROMPT_LABEL
