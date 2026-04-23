# TaskPanel Overview

`TaskPanel` is the backend-workflow control panel shown on the right side of the workspace.

## Core Responsibilities

- Render Step A (`/api/ontology/generate`) and Step B (`/api/build`) flows.
- Drive form input for project context:
  - simulation requirement
  - project name
  - additional context
  - category label
  - graph/chunk settings
- Trigger async actions from `TaskStore`:
  - ontology generate
  - graph build
  - project prompt-label update
  - ontology type update
- Display task progress and status cards for Step A / Step B.
- Show system dashboard logs in the backend tab.

## Editing Workflows Inside TaskPanel

- Ontology type editor:
  - single modal opened from Step A stat cards; Entity Types vs Relationship Types stat picks the active tab
  - tab strip switches between entity and relationship tag lists in one dialog
  - per-tab Edit toggles remove mode (× on each tag); Confirm persists both lists to the project
  - tag-based type name edits
  - nested property editor for metadata/attributes/source-targets
  - JSON validation before confirm
- Category label editor:
  - edit existing label lists
  - create new labels
  - revert to production defaults
  - sync defaults from Langfuse
  - protect against cross-list duplicates:
    - `individual` vs `individual_exception`
    - `organization` vs `organization_exception`
    - `relationship` vs `relationship_exception`

## UI Behaviors

- Endpoint chip click copies full backend URL (`host + path`) and shows short `Copy!` popup.
- Info icon tooltips provide inline help text for endpoint and field semantics.
- Category label dropdown shows:
  - selected marker
  - `P` marker when a label is project-scoped for the current project
- Global `Escape` closes the active top-most editor panel.

## Refactor Notes

- Shared reusable logic moved into `TaskPanel/utils.js`.
- Reusable UI components moved into `frontend/src/components/`:
  - `TypeTagEditor.jsx`
  - `JsonListEditor.jsx`
- Main `TaskPanel/TaskPanel.jsx` now focuses on orchestration/state wiring and rendering flow.
