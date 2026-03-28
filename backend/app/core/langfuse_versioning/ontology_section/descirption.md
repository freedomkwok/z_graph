# Prompt Storage and Override Rules

This document captures the agreed behavior for prompt storage and resolution.

## 1) Prompt Types

- **Base prompts (global only):**
  - `ONTOLOGY_SYSTEM_PROMPT.md`
  - `USER_EXTRACTION_PROMPT.md`
- These 2 are base prompts for ontology flow and should remain base/global prompts.
- They are **not** treated as project override prompts.

## 2) Label-Based Prompt Set (6 prompts)

- The remaining 6 prompts are label-scoped prompts:
  - Entity: `examples` + `exceptions`
  - Organization: `examples` + `exceptions`
  - Relations: `examples` + `exceptions`
- These are stored under label folders (for example `production`, `medical`) in local files and mapped to labeled prompts in Langfuse.

## 3) Global Scope Behavior

- Globally, the system has 8 logical prompts total:
  - 2 base prompts
  - 6 label-based prompts
- If only `production` exists, that acts as the global default label.
- To add another global label (for example `medical`) for a label-based prompt, create the same prompt with label `medical`.

## 4) Project Scope Behavior (Copy-on-Write)

- Project override applies to **only the 6 label-based prompts**.
- If a project has no override for a label-based prompt, backend reads from global.
- When user opens edit for project scope:
  - backend loads effective content (usually global if project override does not exist yet).
- When user saves:
  - backend writes a project-scoped override (copy-on-write).

## 5) Project Prompt Naming/Path

- Confirmed project namespace path format:
  - `prompts/<PROMPT_NAME>/<project_id>`
- Project save should use the currently selected label as the prompt label.

## 6) Effective Resolution Order (Project Context, Label-Based Prompts)

When resolving one of the 6 label-based prompts for a project:

1. Project-scoped prompt + selected label
2. Project-scoped prompt + `production` label
3. Global prompt + selected label
4. Global prompt + `production` label
5. Local file fallback

## 7) Important Constraint

- Do not pre-create project prompt copies.
- Project prompts are created only after user edits and saves.
