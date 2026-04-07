# Ontology Section Prompt Structure

This document defines the current ontology prompt layout and how it maps to Langfuse.

## 1) Local Folder Structure

- Root: `app/core/langfuse_versioning/ontology_section/`
- Base prompts (2 files):
  - `ontology_section/prompts/production/ONTOLOGY_SYSTEM_PROMPT.md`
  - `ontology_section/prompts/production/USER_EXTRACTION_PROMPT.md`
- Label-based prompts (6 files per label):
  - `ontology_section/labels/<label>/ENTITY_EXAMPLES_IN_SYSTEM_PROMPT.md`
  - `ontology_section/labels/<label>/ENTITT_EXCEPTIONS_IN_SYSTEM_PROMPT.md`
  - `ontology_section/labels/<label>/ORGANIZATION_EXAMPLES_IN_SYSTEM_PROMPT.md`
  - `ontology_section/labels/<label>/ORGANIZATION_EXCEPTIONS_IN_SYSTEM_PROMPT.md`
  - `ontology_section/labels/<label>/RELATIONS_EXPCETIONS_IN_SYSTEM_PROMPT.md`
  - `ontology_section/labels/<label>/RELATIONS_IN_SYSTEM_PROMPT copy.md`

## 2) Langfuse Naming Rules

Local structure is intentionally different from Langfuse naming.

- Base prompt upload name:
  - `ontology_section/prompts/<PROMPT_NAME>`
  - Label comes from Langfuse label metadata (inferred from local folder segment, for example `production`).
- Label-based prompt upload name:
  - `ontology_section/labels/<PROMPT_NAME>`
  - Label comes from the local folder name `<label>` (for example `production`, `medical`).

## 3) What You Should See in Langfuse UI

- `ontology_section/prompts/*` (the 2 base prompts), with label metadata
- `ontology_section/labels/*` (the 6 label-based prompts), with label metadata:
  - `production` for files from `ontology_section/labels/production/`
  - another label (for example `medical`) when synced from that label folder

## 4) Global Usage Example

- If only `production` exists, system uses global `production`.
- To add a global medical variant, add the same 6 files under:
  - `ontology_section/labels/medical/`
- After sync, Langfuse keeps the same prompt names under `ontology_section/labels/*`,
  and distinguishes variants by labels (`production`, `medical`, etc.).

## 5) Project Override Retrieval

- Project override applies to the 6 label-based prompts only.
- Base prompts use `ontology_section/prompts/<PROMPT_NAME>` with Langfuse label routing.
- Project-scoped Langfuse prompt name format:
  - `ontology_section/labels/<PROMPT_NAME>/<project_id>`
- Label remains a Langfuse label (for example `production`, `medical`).

Resolution by project context:

1. If `project_id` is not null, try project-scoped prompt first.
2. If missing, fallback to global prompt (`ontology_section/labels/<PROMPT_NAME>`).
3. Then fallback across labels (`requested -> production -> default`).
4. Finally fallback to local files.

If `project_id` is null, retrieval is global-only.
