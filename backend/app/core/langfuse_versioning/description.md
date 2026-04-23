# Langfuse Label Retrieval Logic

This document explains how prompt labels are resolved and retrieved when `PROMPT_BACKEND=langfuse` (with local fallback support).

## Main Components

- `prompt_provider.py`
  - `LangfusePromptProvider.get(...)` is the entry point for Langfuse-backed prompt retrieval.
  - `FallbackPromptProvider.get(...)` adds label fallback and local-file fallback behavior.
- `langfuse_prompt_retriever.py`
  - `LangfusePromptRetriever.get(...)` does candidate building, cache lookup, and `client.get_prompt(...)` calls.
  - `build_local_path_candidates(...)` mirrors label/project fallback behavior for local file fallback.
- `langfuse_category_label_retriever.py`
  - Shared label normalization and fallback helpers:
    - `normalize_label(...)`
    - `build_label_fallback_candidates(...)`
    - `PRODUCTION_LABEL`

## Label Normalization

Every incoming label is normalized before use:

- Empty label -> treated as `None` during candidate building.
- Non-empty label -> normalized by `normalize_label(...)`.
- Provider-level default:
  - `LangfusePromptProvider.get(...)` computes
    `effective_label = normalize_label(label or settings.prompt_label)`.

## Retrieval Flow (High Level)

1. Caller asks prompt provider for `name`, optional `label`, optional `project_id`.
2. `LangfusePromptProvider` delegates to `LangfusePromptRetriever.get(...)`.
3. Retriever builds a prioritized list of prompt-name candidates (including project-scoped and labeled forms).
4. For each prompt-name candidate, retriever builds a label-candidate list.
5. It calls `client.get_prompt(candidate_name, label=candidate_label, version=...)` until one succeeds.
6. If all fail, exception bubbles up; `FallbackPromptProvider` then tries local file fallback with the same label fallback semantics.

## Candidate Name and Label Rules

## 1) Base ontology prompts

Prompt family: `ontology_section/prompts/...`

- Retriever normalizes base name to canonical form:
  - `ontology_section/prompts/<PROMPT_NAME>`
- For project-scoped retrieval:
  - tries `ontology_section/prompts/<project_id>/<label>/<PROMPT_NAME>` first.
- Label fallback order for this family is from `build_label_fallback_candidates(...)`, typically:
  - requested label -> production -> unlabeled fallback.

## 2) Ontology label prompts

Prompt family: `ontology_section/labels/...`

- Supports both project-scoped and non-project-scoped candidates.
- Project-scoped examples:
  - `ontology_section/labels/<project_id>/<label>/<PROMPT_NAME>`
  - `ontology_section/labels/<project_id>/<PROMPT_NAME>`
- Non-project examples:
  - `ontology_section/labels/<label>/<PROMPT_NAME>`
  - `ontology_section/labels/<PROMPT_NAME>`

## 3) Auto-label-generator prompts

Prompt family: `auto_label_generator/prompts/...` (and related labels path handling)

- Similar project + label fallback strategy as ontology prompt families.
- Project-scoped form is preferred when `project_id` is available.

## 4) Other categories (e.g. sub_queries, fallback_entities)

- Label insertion is attempted where supported by naming conventions.
- If unsupported, retriever falls back to plain candidate names.

## Cache Behavior

`LangfusePromptRetriever.get(...)` uses a multi-key cache strategy:

- Primary cache key includes:
  - `prompt_name`, `label`, `project_id`, `version`, and render vars.
- Lookup also checks fallback cache keys built from candidate name/label combinations.
- TTL controls:
  - `prompt_cache_ttl_seconds` (default 300)
  - `prompt_project_miss_ttl_seconds` (default 1800)

This reduces repeated network calls while preserving project/label-specific behavior.

## Langfuse API Call Shape

At retrieval time, the effective call is equivalent to:

- `client.get_prompt(name, version=..., label=...)`

If the returned object has `compile(...)`, it is rendered with `vars`; otherwise it is cast to string.

## Fallback Provider Behavior

`FallbackPromptProvider.get(...)` wraps primary + local fallback:

1. Try primary provider (Langfuse) across label fallback candidates.
2. If all fail or content is invalid/empty, log warning and try local file provider using same label candidates.
3. Local provider uses `build_local_path_candidates(...)` to mirror project/label resolution.

## Related Write/Sync Paths

Besides runtime retrieval, there are direct Langfuse REST read/write helpers used by management/sync tooling:

- `prompt_label_manager.py`
  - `_fetch_langfuse_prompt_text(...)` uses `/api/public/v2/prompts/{name}?label=...`
  - `_upsert_langfuse_prompt(...)` posts prompt content with labels.
- `scripts/sync_from_langfuse.py`
  - `_fetch_prompt_payload(...)` and `_fetch_prompt_text(...)` use label query params to pull prompt content.

These paths are complementary to runtime retrieval and follow the same label concept.

## Practical Summary

- Label resolution is not a single hardcoded path; it is a prioritized candidate search over:
  - prompt name forms (base/project/labeled variants)
  - label fallbacks (requested -> production -> unlabeled)
- Runtime retrieval is centered in:
  - `LangfusePromptProvider` -> `LangfusePromptRetriever`
- Local fallback uses:
  - `FallbackPromptProvider` + `FilePromptProvider` + `build_local_path_candidates(...)`
