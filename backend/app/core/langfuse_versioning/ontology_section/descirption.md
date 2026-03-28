# Ontology Section Prompt Structure

This document defines the current ontology prompt layout and how it maps to Langfuse.

## 1) Local Folder Structure

- Root: `app/core/langfuse_versioning/ontology_section/`
- Base prompts (2 files):
  - `ontology_section/prompts/ONTOLOGY_SYSTEM_PROMPT.md`
  - `ontology_section/prompts/USER_EXTRACTION_PROMPT.md`
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
  - No label required.
- Label-based prompt upload name:
  - `ontology_section/labels/<PROMPT_NAME>`
  - Label comes from the local folder name `<label>` (for example `production`, `medical`).

## 3) What You Should See in Langfuse UI

- `ontology_section/prompts/*` (the 2 base prompts)
- `ontology_section/labels/*` (the 6 label-based prompts), with label metadata:
  - `production` for files from `ontology_section/labels/production/`
  - another label (for example `medical`) when synced from that label folder

## 4) Global Usage Example

- If only `production` exists, system uses global `production`.
- To add a global medical variant, add the same 6 files under:
  - `ontology_section/labels/medical/`
- After sync, Langfuse keeps the same prompt names under `ontology_section/labels/*`,
  and distinguishes variants by labels (`production`, `medical`, etc.).
