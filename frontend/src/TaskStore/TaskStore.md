# TaskStore Architecture

This folder contains the frontend global task/project store used by:

- Step A (ontology generation)
- Step B (graph build)
- Project + prompt label management
- System Dashboard logs + task polling

`frontend/src/taskStore.jsx` has been removed. Import from `frontend/src/TaskStore/index.js`.

## File Map

- `TaskStoreProvider.jsx`
  - React context provider and `useTaskStore()`.
  - Wires all action modules into one public store API.
  - Contains polling effects:
    - ontology task polling (`/api/task/:taskId`)
    - graph task polling (`/api/task/:taskId`)
    - initial boot effect (health + prompt labels + projects)
  - Function to append latency events to dashboard logs.

- `state.js`
  - `initialOntologyTask`, `initialGraphTask`, `initialState`
  - `taskReducer(state, action)`
  - `getOntologyTaskFromProject(project)`
  - `getGraphTaskFromProject(project)`

- `constants.js`
  - API base resolution and backend display URL.
  - Shared constants:
    - `withApiBase(path)`
    - `BACKEND_DISPLAY_URL`
    - `LAST_PROJECT_ID_KEY`
    - `MAX_SYSTEM_LOGS`

- `storage.js`
  - Local storage helpers:
    - `rememberLastProjectId(projectId)`
    - `readLastProjectId()`

- `utils.js`
  - Shared utility helpers:
    - ID/number normalization
    - prompt label fallback resolver
    - API JSON parsing helper
    - graph data URL builder
    - ontology type normalization and merge logic
      (`buildUpdatedOntologyFromTypeNames`)

- `actions/promptLabelActions.js`
  - Prompt label APIs:
    - list/create/delete labels
    - sync label from Langfuse

- `actions/projectActions.js`
  - Project APIs and project-derived UI state:
    - switch/fetch/refresh projects
    - update project name
    - delete project
    - update project prompt label
    - persist edited ontology types (`updateProjectOntologyTypes`)

- `actions/ontologyActions.js`
  - Step A submit flow:
    - validate form/files
    - submit `/api/ontology/generate`
    - start ontology task tracking

- `actions/graphActions.js`
  - Step B submit flow:
    - validate graph build request
    - submit `/api/build`
    - start graph task tracking

- `actions/healthActions.js`
  - Backend health check flow:
    - `/api/health`
    - follow-up `/api/project/list?limit=1` sanity check

## Public Store API

Exposed from `useTaskStore()`:

- **State + basic setters**
  - `state`
  - `setViewMode`
  - `refreshGraphFrame`
  - `setFormField`
  - `setFiles`
  - `addSystemLog`

- **Prompt label actions**
  - `fetchPromptLabels`
  - `createPromptLabel`
  - `deletePromptLabel`
  - `syncPromptLabelFromLangfuse`

- **Project actions**
  - `switchProject`
  - `fetchProjects`
  - `refreshProjects`
  - `updateProjectName`
  - `deleteProject`
  - `setProjectPromptLabel`
  - `updateProjectOntologyTypes`

- **Task actions**
  - `checkBackendHealth`
  - `runOntologyGenerate`
  - `runGraphBuild`

## Notes

- Polling behavior and task state transitions remain unchanged from the previous monolithic store.
- Latency event logging for Step A/Step B still reads `task.progress_detail.latency_events`.
- `taskStore.jsx` remains the import path for compatibility, but all logic should be added under `TaskStore/*`.
