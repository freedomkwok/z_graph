"""
Auto-generate prompt label type lists from document text.
"""

import re
from json import JSONDecodeError, loads
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Config
from app.core.langfuse_versioning.prompt_provider import PromptProvider, make_prompt_provider
from app.core.llm.factory import create_openai_provider
from app.core.llm.providers.openai.provider import OpenAIProvider
from app.core.llm.types import LLMRequest


class AutoLabelGeneratorBaseOutput(BaseModel):
    """Canonical payload for generated ontology label types."""

    model_config = ConfigDict(extra="forbid")

    document_summary: str = Field(default="")
    individual: list[str] = Field(default_factory=list)
    individual_exception: list[str] = Field(default_factory=list)
    organization: list[str] = Field(default_factory=list)
    organization_exception: list[str] = Field(default_factory=list)
    relationship: list[str] = Field(default_factory=list)
    relationship_exception: list[str] = Field(default_factory=list)


class AutoLabelGeneratorOutput(AutoLabelGeneratorBaseOutput):
    """Strict LLM output contract for auto label generation."""


class AutoLabelGenerator:
    """Generate category label type lists using an LLM."""

    PROMPT_TEMPLATE_NAME = "auto_label_generator/prompts/production/ENTITY_EDGE_GENERATOR.md"
    MAX_TEXT_LENGTH_FOR_LLM = 50_000

    def __init__(
        self,
        llm_provider: OpenAIProvider | None = None,
        prompt_provider: PromptProvider | None = None,
    ) -> None:
        self.llm = llm_provider or create_openai_provider(
            model=Config.LLM_MODEL_NAME,
            api_key=Config.LLM_API_KEY,
            base_url=Config.LLM_BASE_URL,
        )
        base_dir = Path(__file__).resolve().parent.parent / "langfuse_versioning"
        self.prompt_provider = prompt_provider or make_prompt_provider(prompts_dir=base_dir)

    def generate(
        self,
        *,
        document_texts: list[str],
        label_name: str,
        project_id: str | None = None,
        entity_edge_generator_prompt_content: str | None = None,
    ) -> dict[str, Any]:
        normalized_documents = [
            str(document_text).strip()
            for document_text in document_texts
            if str(document_text).strip()
        ]
        if not normalized_documents:
            raise ValueError("No document text available for LLM label generation")

        user_prompt = self._build_user_prompt(
            document_texts=normalized_documents,
            label_name=label_name,
            project_id=project_id,
            entity_edge_generator_prompt_content=entity_edge_generator_prompt_content,
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You generate ontology category label lists from document context. "
                    "Return JSON only and follow the requested schema exactly."
                ),
            },
            {"role": "user", "content": user_prompt},
        ]
        llm_response = self.llm.generate(
            LLMRequest(
                messages=messages,
                temperature=0.3,
                max_tokens=4096,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "auto_label_generator_output",
                        "schema": AutoLabelGeneratorOutput.model_json_schema(),
                    },
                },
                operation="label_generation",
                metadata={
                    "component": "auto_label_generator",
                    "label_name": label_name,
                    "project_id": str(project_id or ""),
                },
            )
        )
        try:
            response_payload = loads(str(llm_response.text or "{}"))
        except JSONDecodeError as exc:
            raise ValueError("LLM output is not valid JSON") from exc

        if not isinstance(response_payload, dict):
            raise ValueError("LLM output must be a JSON object")

        try:
            validated_output = AutoLabelGeneratorOutput.model_validate(response_payload)
        except ValidationError as exc:
            raise ValueError(
                "LLM output does not match AutoLabelGeneratorOutput schema"
            ) from exc
        return validated_output.model_dump()

    def _build_user_prompt(
        self,
        *,
        document_texts: list[str],
        label_name: str,
        project_id: str | None,
        entity_edge_generator_prompt_content: str | None = None,
    ) -> str:
        combined_text = self._truncate_text("\n\n---\n\n".join(document_texts))
        override_template = str(entity_edge_generator_prompt_content or "").strip()
        if override_template:
            return self._render_override_template(
                override_template,
                label_name=label_name,
                combined_text=combined_text,
            )

        base_prompt = self.prompt_provider.get(
            self.PROMPT_TEMPLATE_NAME,
            project_id=project_id,
            label_name=label_name,
            combined_text=combined_text,
        )
        return base_prompt

    @staticmethod
    def _render_override_template(
        template: str,
        *,
        label_name: str,
        combined_text: str,
    ) -> str:
        rendered = str(template or "")
        replacements = {
            "label_name": str(label_name or ""),
            "combined_text": str(combined_text or ""),
        }
        for variable_name, value in replacements.items():
            pattern = re.compile(r"\{\{\s*" + re.escape(variable_name) + r"\s*\}\}")
            rendered = pattern.sub(value, rendered)
        return rendered

    @classmethod
    def _truncate_text(cls, text: str) -> str:
        if len(text) <= cls.MAX_TEXT_LENGTH_FOR_LLM:
            return text

        return (
            text[: cls.MAX_TEXT_LENGTH_FOR_LLM]
            + "\n\n...(input truncated for LLM auto-label generation)..."
        )

    @classmethod
    def _normalize_response_payload(
        cls,
        payload: AutoLabelGeneratorOutput,
    ) -> dict[str, Any]:
        return {
            "document_summary": payload.document_summary,
            "individual": payload.person_types,
            "individual_exception": [],
            "organization": payload.organization_types,
            "organization_exception": [],
            "relationship": payload.relationship_types,
            "relationship_exception": [],
        }
