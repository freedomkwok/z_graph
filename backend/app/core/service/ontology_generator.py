"""
Ontology generation service.
API 1: analyze text and emit entity/relation type definitions.
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.core.langfuse_versioning.prompt_provider import PromptProvider, make_prompt_provider
from app.core.utils.llm_client import LLMClient


class OntologyGenerator:
    """
    Builds ontology definitions from documents and contextual requirements.
    """
    
    PROMPT_LABEL = "Production"
    USER_EXTRACTION_PROMPT_NAME = "USER_EXTRACTION_PROMPT.md"
    ONTOLOGY_SYSTEM_PROMPT_NAME = "ONTOLOGY_SYSTEM_PROMPT.md"
    PERSON_FALLBACK_NAME = "person.json"
    ORGANIZATION_FALLBACK_NAME = "organization.json"
    _PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        prompt_provider: Optional[PromptProvider] = None,
        fallback_entity_provider: Optional[PromptProvider] = None,
    ):
        self.llm_client = llm_client or LLMClient()
        base_dir = Path(__file__).resolve().parent.parent / "langfuse_versioning"
        default_prompts_dir = base_dir / "prompts"
        default_fallback_entity_dir = base_dir / "fallback_entites"
        self.prompt_provider = prompt_provider or make_prompt_provider(prompts_dir=default_prompts_dir)
        self.fallback_entity_provider = fallback_entity_provider or make_prompt_provider(
            prompts_dir=default_fallback_entity_dir
        )
        # Keep a local baseline after providers are configured.
        self.DEFAULT_SYSTEM_PROMPT = self._load_local_system_prompt(default_prompts_dir)
    
    def generate(
        self,
        document_texts: List[str],
        context_requirement: str = "",
        additional_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate an ontology dict (entity_types, edge_types, etc.).

        Args:
            document_texts: Document bodies
            context_requirement: Requirement/context text
            additional_context: Optional extra context

        Returns:
            Parsed ontology definition
        """
        # Build user message
        user_message = self._build_user_message(
            document_texts, 
            context_requirement,
            additional_context
        )
        
        messages = [
            {"role": "system", "content": self._get_system_prompt()},
            {"role": "user", "content": user_message}
        ]
        
        # Call LLM
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,
            max_tokens=4096
        )
        
        # Validate and post-process
        result = self._validate_and_process(result)
        
        return result
    
    # Max characters sent to the LLM (~50k Chinese chars)
    MAX_TEXT_LENGTH_FOR_LLM = 50000
    
    def _build_user_message(
        self,
        document_texts: List[str],
        context_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """Assemble the user message payload."""
        
        # Merge documents
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)
        
        # Truncate if over limit (LLM input only; graph build uses full text elsewhere)
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += (
                f"\n\n...(Total length: {original_length} chars; "
                f"only first {self.MAX_TEXT_LENGTH_FOR_LLM} chars included for ontology analysis)..."
            )

        return self.prompt_provider.get(
            self.USER_EXTRACTION_PROMPT_NAME,
            label=self.PROMPT_LABEL,
            context_requirement=context_requirement or "未提供",
            combined_text=combined_text,
            additional_context=additional_context or "未提供",
        )

    def _get_system_prompt(self) -> str:
        template = self.DEFAULT_SYSTEM_PROMPT
        placeholder_vars = self._build_system_prompt_placeholder_vars(template)

        try:
            prompt = self.prompt_provider.get(
                self.ONTOLOGY_SYSTEM_PROMPT_NAME,
                label=self.PROMPT_LABEL,
                **placeholder_vars,
            )
            prompt = self._render_dynamic_placeholders(prompt or "", placeholder_vars).strip()
            return prompt or template
        except Exception:
            return self._render_dynamic_placeholders(template, placeholder_vars).strip() or template

    def _load_local_system_prompt(self, prompts_dir: Path) -> str:
        candidates = [
            prompts_dir / self.ONTOLOGY_SYSTEM_PROMPT_NAME,
            prompts_dir / self.ONTOLOGY_SYSTEM_PROMPT_NAME.lower(),
        ]
        for path in candidates:
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except Exception:
                continue
        return self.DEFAULT_SYSTEM_PROMPT

    def _build_system_prompt_placeholder_vars(self, template: str) -> Dict[str, str]:
        placeholder_vars: Dict[str, str] = {}
        for key in self._extract_placeholder_keys(template):
            value = self._load_system_prompt_fragment(key)
            if value:
                placeholder_vars[key] = value
        return placeholder_vars

    def _extract_placeholder_keys(self, template: str) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for match in self._PLACEHOLDER_PATTERN.finditer(template):
            key = match.group(1)
            if key not in seen:
                seen.add(key)
                ordered.append(key)
        return ordered

    def _render_dynamic_placeholders(self, template: str, placeholder_vars: Dict[str, str]) -> str:
        def replacer(match: re.Match[str]) -> str:
            key = match.group(1)
            return placeholder_vars.get(key, match.group(0))

        return self._PLACEHOLDER_PATTERN.sub(replacer, template)

    def _load_system_prompt_fragment(self, placeholder_key: str) -> str:
        for prompt_name in self._candidate_prompt_names_for_placeholder(placeholder_key):
            try:
                fragment = self.prompt_provider.get(prompt_name, label=self.PROMPT_LABEL)
                fragment = (fragment or "").strip()
                if fragment:
                    return fragment
            except Exception:
                continue
        return ""

    def _candidate_prompt_names_for_placeholder(self, placeholder_key: str) -> List[str]:
        aliases: List[str] = []

        def add_alias(name: str) -> None:
            if name and name not in aliases:
                aliases.append(name)

        add_alias(placeholder_key)

        if "ORGANIZATIONS_" in placeholder_key:
            add_alias(placeholder_key.replace("ORGANIZATIONS_", "ORGANIZATION_", 1))
        if "ORGANIZATION_" in placeholder_key:
            add_alias(placeholder_key.replace("ORGANIZATION_", "ORGANIZATIONS_", 1))
        if "ENTITIES_" in placeholder_key:
            add_alias(placeholder_key.replace("ENTITIES_", "ENTITES_", 1))
        if "ENTITES_" in placeholder_key:
            add_alias(placeholder_key.replace("ENTITES_", "ENTITIES_", 1))

        names: List[str] = []
        for alias in aliases:
            names.append(f"{alias}.md")
            names.append(f"{alias}.MD")
        return names
    
    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate shape and enforce Zep limits."""
        
        # Ensure required keys
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""
        
        # Entity types
        for entity in result["entity_types"]:
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # Cap description length
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."
        
        # Edge types
        for edge in result["edge_types"]:
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."
        
        # Zep API: at most 10 custom entity types and 10 custom edge types
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10
        
        # Fallback entity types: provider first (Production), then local JSON files.
        # Extension point: this can be replaced by a DB-backed source later.
        person_fallback = self._load_fallback_entity(self.PERSON_FALLBACK_NAME)
        organization_fallback = self._load_fallback_entity(self.ORGANIZATION_FALLBACK_NAME)
        
        # Check for fallback types
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

    def _load_fallback_entity(self, file_name: str) -> Dict[str, Any]:
        """
        Resolve fallback entity definition:
        1) Prompt provider with label=Production (remote first)
        2) Local JSON via provider fallback
        """
        try:
            raw = self.fallback_entity_provider.get(file_name, label=self.PROMPT_LABEL)
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
