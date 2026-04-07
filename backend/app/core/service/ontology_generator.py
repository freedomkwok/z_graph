"""
Ontology generation service.
API 1: analyze text and emit entity/relation type definitions.
"""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import Config
from app.core.langfuse_versioning.prompt_provider import PromptProvider, make_prompt_provider
from app.core.llm.factory import create_openai_provider
from app.core.llm.providers.openai.provider import OpenAIProvider
from app.core.llm.types import LLMRequest


class OntologyGeneratorOutput(BaseModel):
    """Strict output contract for ontology generation responses."""

    model_config = ConfigDict(extra="ignore")

    analysis_summary: str = Field(default="")
    entity_types: list[dict[str, Any]] = Field(default_factory=list)
    edge_types: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("analysis_summary", mode="before")
    @classmethod
    def _normalize_analysis_summary(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("entity_types", "edge_types", mode="before")
    @classmethod
    def _normalize_type_definitions(cls, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Ontology type fields must be arrays of objects")
        return [item for item in value if isinstance(item, dict)]


class OntologyGenerator:
    """
    Builds ontology definitions from documents and contextual requirements.
    """

    DEFAULT_PROMPT_LABEL = "Production"
    # Label-aware resolution:
    # requested label -> production -> default/local fallback.
    # Local default files live under ontology_section/prompts/production/.
    ONTOLOGY_OUTPUT_EXTRACTION_PROMPT_NAME = "ontology_section/prompts/USER_EXTRACTION_PROMPT.md"
    ONTOLOGY_SYSTEM_PROMPT_NAME = "ontology_section/prompts/ONTOLOGY_SYSTEM_PROMPT.md"
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
        # Unified root so ontology_section/* and fallback_entities/* resolve identically
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
        minimum_nodes: int = 10,
        minimum_edges: int = 10,
        prompt_label: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        effective_prompt_label = self._normalize_prompt_label(prompt_label)
        effective_project_id = str(project_id or "").strip() or None
        normalized_minimum_nodes = self._normalize_minimum_count(minimum_nodes)
        normalized_minimum_edges = self._normalize_minimum_count(minimum_edges)
        # Build user message
        user_message = self._build_user_message(
            document_texts,
            context_requirement,
            additional_context,
            minimum_nodes=normalized_minimum_nodes,
            minimum_edges=normalized_minimum_edges,
            prompt_label=effective_prompt_label,
            project_id=effective_project_id,
        )

        messages = [
            {
                "role": "system",
                "content": self._get_system_prompt(
                    prompt_label=effective_prompt_label,
                    project_id=effective_project_id,
                ),
            },
            {"role": "user", "content": user_message},
        ]

        llm_response = self.llm.generate(
            LLMRequest(
                messages=messages,
                temperature=0.3,
                max_tokens=12096,
                response_format={"type": "json_object"},
                operation="Ontology_Creation",
                metadata={
                    "component": "ontology_generator",
                    "project_id": str(effective_project_id or ""),
                    "prompt_label": effective_prompt_label,
                },
            )
        )
        try:
            validated_output = OntologyGeneratorOutput.model_validate_json(llm_response.text)
        except ValidationError as exc:
            raise ValueError(
                "LLM output does not match OntologyGeneratorOutput schema"
            ) from exc

        result = validated_output.model_dump()
        result = self._faillback_process(
            result,
            minimum_nodes=normalized_minimum_nodes,
            minimum_edges=normalized_minimum_edges,
            prompt_label=effective_prompt_label,
            project_id=effective_project_id,
        )

        return result

    # Max characters sent to the LLM (~50k Chinese chars)
    MAX_TEXT_LENGTH_FOR_LLM = 50000

    def _build_user_message(
        self,
        document_texts: list[str],
        context_requirement: str,
        additional_context: str | None,
        minimum_nodes: int,
        minimum_edges: int,
        prompt_label: str,
        project_id: str | None,
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
            self.ONTOLOGY_OUTPUT_EXTRACTION_PROMPT_NAME,
            label=prompt_label,
            project_id=project_id,
            context_requirement=context_requirement or "Not provided",
            combined_text=combined_text,
            additional_context=additional_context or "Not provided",
            minimum_nodes=str(minimum_nodes),
            minimum_edges=str(minimum_edges),
        )

    def _get_system_prompt(self, prompt_label: str, *, project_id: str | None) -> str:
        template = self.prompt_provider.get(
            self.ONTOLOGY_SYSTEM_PROMPT_NAME,
            label=prompt_label,
            project_id=project_id,
        )
        placeholder_vars = self._build_system_prompt_placeholder_vars(
            template,
            prompt_label=prompt_label,
            project_id=project_id,
        )
        # Single source of truth: render the already-loaded template in-memory.
        return self._render_dynamic_placeholders(template or "", placeholder_vars).strip()

    def _build_system_prompt_placeholder_vars(
        self,
        template: str,
        *,
        prompt_label: str,
        project_id: str | None,
    ) -> dict[str, str]:
        placeholder_vars: dict[str, str] = {}
        for key in self._extract_placeholder_keys(template):
            normalized_key = self._normalize_placeholder_key(key)
            value = self._load_system_prompt_fragment(
                normalized_key,
                prompt_label=prompt_label,
                project_id=project_id,
            )
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

    def _load_system_prompt_fragment(
        self,
        placeholder_key: str,
        *,
        prompt_label: str,
        project_id: str | None,
    ) -> str:
        prompt_name = f"ontology_section/labels/{placeholder_key}.md"
        try:
            fragment = self.prompt_provider.get(
                prompt_name,
                label=prompt_label,
                project_id=project_id,
            )
            fragment = (fragment or "").strip()
            if fragment:
                return fragment
        except Exception:
            return ""
        return ""

    def _faillback_process(
        self,
        result: dict[str, Any],
        *,
        minimum_nodes: int,
        minimum_edges: int,
        prompt_label: str,
        project_id: str | None,
    ) -> dict[str, Any]:
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

        minimum_entity_types = self._normalize_minimum_count(minimum_nodes)
        minimum_edge_types = self._normalize_minimum_count(minimum_edges)
        max_entity_types = max(minimum_entity_types, 10)
        max_edge_types = max(minimum_edge_types, 10)

        person_fallback = self._load_fallback_entity(
            self.PERSON_FALLBACK_NAME,
            prompt_label=prompt_label,
            project_id=project_id,
        )
        organization_fallback = self._load_fallback_entity(
            self.ORGANIZATION_FALLBACK_NAME,
            prompt_label=prompt_label,
            project_id=project_id,
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
            if current_count + needed_slots > max_entity_types:
                to_remove = current_count + needed_slots - max_entity_types
                # Remove from the end (keep earlier specific types)
                result["entity_types"] = result["entity_types"][:-to_remove]

            result["entity_types"].extend(fallbacks_to_add)

        # Hard cap (defensive)
        if len(result["entity_types"]) > max_entity_types:
            result["entity_types"] = result["entity_types"][:max_entity_types]

        if len(result["edge_types"]) > max_edge_types:
            result["edge_types"] = result["edge_types"][:max_edge_types]

        self._ensure_minimum_entity_types(result["entity_types"], minimum_entity_types)
        self._ensure_minimum_edge_types(
            result["edge_types"],
            result["entity_types"],
            minimum_edge_types,
        )

        return result

    @staticmethod
    def _normalize_minimum_count(value: Any, default: int = 10) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        if parsed < 1:
            return default
        return min(parsed, 200)

    @staticmethod
    def _ensure_minimum_entity_types(entity_types: list[dict[str, Any]], minimum_count: int) -> None:
        existing_names = {
            str(entity.get("name", "")).strip().lower()
            for entity in entity_types
            if isinstance(entity, dict)
        }
        cursor = 1
        while len(entity_types) < minimum_count:
            candidate_name = f"EntityType{cursor}"
            candidate_key = candidate_name.lower()
            cursor += 1
            if candidate_key in existing_names:
                continue
            entity_types.append(
                {
                    "name": candidate_name,
                    "description": "Autogenerated entity type to satisfy minimum node count.",
                    "attributes": [],
                    "examples": [],
                }
            )
            existing_names.add(candidate_key)

    @staticmethod
    def _ensure_minimum_edge_types(
        edge_types: list[dict[str, Any]],
        entity_types: list[dict[str, Any]],
        minimum_count: int,
    ) -> None:
        existing_names = {
            str(edge.get("name", "")).strip().upper()
            for edge in edge_types
            if isinstance(edge, dict)
        }
        entity_names = [
            str(entity.get("name", "")).strip()
            for entity in entity_types
            if isinstance(entity, dict) and str(entity.get("name", "")).strip()
        ]
        default_source = entity_names[0] if entity_names else "Person"
        default_target = entity_names[1] if len(entity_names) > 1 else default_source

        cursor = 1
        while len(edge_types) < minimum_count:
            candidate_name = f"RELATES_TO_{cursor}"
            cursor += 1
            if candidate_name in existing_names:
                continue
            edge_types.append(
                {
                    "name": candidate_name,
                    "description": "Autogenerated edge type to satisfy minimum edge count.",
                    "source_targets": [{"source": default_source, "target": default_target}],
                    "attributes": [],
                }
            )
            existing_names.add(candidate_name)

    def _load_fallback_entity(
        self,
        file_name: str,
        *,
        prompt_label: str,
        project_id: str | None,
    ) -> dict[str, Any]:
        """
        Resolve fallback entity definition:
        1) Prompt provider with label=Production (remote first)
        2) Local JSON via provider fallback
        """
        try:
            raw = self.fallback_entity_provider.get(
                file_name,
                label=prompt_label,
                project_id=project_id,
            )
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
