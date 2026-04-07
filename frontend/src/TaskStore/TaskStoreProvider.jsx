import { createContext, useContext, useEffect, useReducer, useRef } from "react";

import { withApiBase } from "./constants";
import { createGraphActions } from "./actions/graphActions";
import { createHealthActions } from "./actions/healthActions";
import { createOntologyActions } from "./actions/ontologyActions";
import { createProjectActions } from "./actions/projectActions";
import { createPromptLabelActions } from "./actions/promptLabelActions";
import { initialOntologyTask, initialState, taskReducer } from "./state";
import { rememberLastProjectId } from "./storage";
import { normalizeProjectId } from "./utils";

const TaskStoreContext = createContext(null);
const MAX_TASK_POLL_ERROR_RETRIES = 3;

export function TaskStoreProvider({ children }) {
  const [state, dispatch] = useReducer(taskReducer, initialState);
  const lastOntologyTaskMessageRef = useRef("");
  const lastGraphTaskMessageRef = useRef("");
  const seenOntologyLatencyEventIdsRef = useRef(new Set());
  const seenGraphLatencyEventIdsRef = useRef(new Set());

  const addSystemLog = (message) => {
    if (!message) return;
    dispatch({ type: "ADD_SYSTEM_LOG", payload: message });
  };

  const appendTaskLatencyLogs = (task, seenEventsRef, stepLabel) => {
    const latencyEvents = Array.isArray(task?.progress_detail?.latency_events)
      ? task.progress_detail.latency_events
      : [];

    for (const event of latencyEvents) {
      const operation = String(event?.operation ?? "").trim();
      if (!operation) continue;

      const eventId = String(event?.event_id ?? "").trim();
      const fallbackId = `${operation}:${String(event?.elapsed_ms ?? "")}:${String(event?.timestamp ?? "")}`;
      const dedupeId = eventId || fallbackId;
      if (!dedupeId || seenEventsRef.current.has(dedupeId)) continue;
      seenEventsRef.current.add(dedupeId);

      const elapsedMs = Number(event?.elapsed_ms);
      const elapsedText = Number.isFinite(elapsedMs)
        ? `${elapsedMs.toFixed(2)}ms`
        : `${String(event?.elapsed_ms ?? "-")}ms`;
      addSystemLog(`[Latency][${stepLabel}] ${operation}: ${elapsedText}`);
    }
  };

  const setViewMode = (mode) => {
    dispatch({ type: "SET_VIEW_MODE", payload: mode });
  };

  const refreshGraphFrame = () => {
    dispatch({ type: "INCREMENT_IFRAME_VERSION" });
  };

  const setFormField = (field, value) => {
    dispatch({ type: "SET_FORM_FIELD", field, value });
  };

  const setFiles = (files) => {
    dispatch({ type: "SET_FILES", payload: files });
  };

  const setFormFields = (fields) => {
    dispatch({ type: "SET_FORM_FIELDS", payload: fields });
  };

  const promptLabelActions = createPromptLabelActions({
    state,
    dispatch,
    addSystemLog,
    setFormField,
    withApiBase,
  });

  const projectActions = createProjectActions({
    state,
    dispatch,
    addSystemLog,
    setFormField,
    setFormFields,
    withApiBase,
    lastOntologyTaskMessageRef,
    lastGraphTaskMessageRef,
    seenOntologyLatencyEventIdsRef,
    seenGraphLatencyEventIdsRef,
  });

  const healthActions = createHealthActions({
    dispatch,
    addSystemLog,
    withApiBase,
  });

  const ontologyActions = createOntologyActions({
    state,
    dispatch,
    addSystemLog,
    withApiBase,
    seenOntologyLatencyEventIdsRef,
    lastOntologyTaskMessageRef,
  });

  const graphActions = createGraphActions({
    state,
    dispatch,
    addSystemLog,
    withApiBase,
    seenGraphLatencyEventIdsRef,
    lastGraphTaskMessageRef,
    fetchProjects: projectActions.fetchProjects,
  });

  useEffect(() => {
    addSystemLog("Project view initialized.");
    healthActions.checkBackendHealth();
    promptLabelActions.fetchPromptLabels({ syncFormLabel: true }).then(() => {
      projectActions.fetchProjects(undefined, true);
    });
    const timer = setInterval(healthActions.checkBackendHealth, 30000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!state.ontologyTask.taskId) return undefined;

    let cancelled = false;
    const { taskId } = state.ontologyTask;
    let ontologyPollErrorCount = 0;
    addSystemLog(`Polling ontology task ${taskId}...`);

    const poll = async () => {
      try {
        const response = await fetch(withApiBase(`/api/task/${taskId}`));
        const payload = await response.json();
        if (!response.ok || !payload?.success) {
          throw new Error(payload?.error ?? "Ontology task polling failed");
        }

        const task = payload.data;
        if (cancelled) return;
        ontologyPollErrorCount = 0;
        appendTaskLatencyLogs(task, seenOntologyLatencyEventIdsRef, "Step A");

        if (task.message && task.message !== lastOntologyTaskMessageRef.current) {
          lastOntologyTaskMessageRef.current = task.message;
          addSystemLog(task.message);
        }

        const progressProjectId = normalizeProjectId(task?.progress_detail?.project_id ?? "");
        if (progressProjectId && progressProjectId !== normalizeProjectId(state.form.projectId)) {
          dispatch({
            type: "SET_FORM_FIELDS",
            payload: {
              projectId: progressProjectId,
            },
          });
          rememberLastProjectId(progressProjectId);
        }

        if (task.status === "completed") {
          const nextProjectId = normalizeProjectId(task?.result?.project_id ?? progressProjectId);
          const entityTypes = task?.result?.ontology?.entity_types?.length ?? 0;
          const edgeTypes = task?.result?.ontology?.edge_types?.length ?? 0;

          dispatch({
            type: "SET_ONTOLOGY_TASK",
            payload: {
              ...initialOntologyTask,
              status: "success",
              message:
                task.message ??
                (nextProjectId ? `Ontology generated for ${nextProjectId}` : "Ontology generated"),
              progress: 100,
              startedAt: "",
              entityTypes,
              edgeTypes,
            },
          });

          dispatch({
            type: "PATCH_GRAPH_TASK",
            payload: {
              status: "idle",
              message: "Ready to build graph",
              progress: 0,
              taskId: "",
            },
          });

          if (nextProjectId) {
            dispatch({
              type: "SET_FORM_FIELDS",
              payload: {
                projectId: nextProjectId,
                graphName: "",
              },
            });
            rememberLastProjectId(nextProjectId);
            addSystemLog(`Ontology generated for ${nextProjectId}.`);
            await projectActions.switchProject(nextProjectId);
            await projectActions.fetchProjects(nextProjectId, false);
          } else {
            addSystemLog("Ontology generated.");
          }
          return;
        }

        if (task.status === "failed") {
          dispatch({
            type: "PATCH_ONTOLOGY_TASK",
            payload: {
              status: "error",
              message: task.error ?? task.message ?? "Ontology generation failed",
              taskId: "",
              progress: 100,
              startedAt: "",
            },
          });
          addSystemLog(`Ontology generation failed: ${task.error ?? "Unknown error"}`);
          return;
        }

        dispatch({
          type: "PATCH_ONTOLOGY_TASK",
          payload: {
            status: "running",
            message: task.message ?? "Generating ontology...",
            progress: task.progress ?? 0,
            startedAt: String(task?.created_at ?? "").trim(),
          },
        });
      } catch (error) {
        if (cancelled) return;
        ontologyPollErrorCount += 1;
        const errorText = String(error);
        if (ontologyPollErrorCount < MAX_TASK_POLL_ERROR_RETRIES) {
          addSystemLog(
            `Polling ontology task failed (${ontologyPollErrorCount}/${MAX_TASK_POLL_ERROR_RETRIES}), retrying: ${errorText}`,
          );
          return;
        }
        addSystemLog(
          `Exception in pollOntologyTaskStatus after ${MAX_TASK_POLL_ERROR_RETRIES} retries: ${errorText}`,
        );
        dispatch({
          type: "PATCH_ONTOLOGY_TASK",
          payload: {
            status: "error",
            message: errorText,
            taskId: "",
            startedAt: "",
          },
        });
      }
    };

    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [state.ontologyTask.taskId]);

  useEffect(() => {
    if (!state.graphTask.taskId) return undefined;

    let cancelled = false;
    const { taskId } = state.graphTask;
    let graphPollErrorCount = 0;
    addSystemLog(`Polling task ${taskId}...`);

    const poll = async () => {
      try {
        const response = await fetch(withApiBase(`/api/task/${taskId}`));
        const payload = await response.json();
        if (!response.ok || !payload?.success) {
          throw new Error(payload?.error ?? "Task polling failed");
        }

        const task = payload.data;
        if (cancelled) return;
        graphPollErrorCount = 0;
        appendTaskLatencyLogs(task, seenGraphLatencyEventIdsRef, "Step B");
        if (task.message && task.message !== lastGraphTaskMessageRef.current) {
          lastGraphTaskMessageRef.current = task.message;
          addSystemLog(task.message);
        }

        if (task.status === "completed") {
          const completedGraphId = task.result?.zep_graph_id ?? task.result?.graph_id ?? "";
          dispatch({
            type: "PATCH_GRAPH_TASK",
            payload: {
              status: "success",
              message: task.message ?? "Graph build completed",
              progress: 100,
              taskId: "",
              nodeCount: task.result?.node_count ?? 0,
              edgeCount: task.result?.edge_count ?? 0,
              chunkCount: task.result?.chunk_count ?? 0,
            },
          });
          if (completedGraphId) {
            dispatch({
              type: "PATCH_CURRENT_PROJECT",
              payload: {
                graph_id: completedGraphId,
                zep_graph_id: completedGraphId,
                graph_backend: task.result?.graph_backend ?? state.currentProject?.graph_backend ?? "",
                project_workspace_id: task.result?.project_workspace_id ?? "",
                zep_graph_address: task.result?.zep_graph_address ?? "",
                status: "graph_completed",
              },
            });
          }
          addSystemLog("Graph build completed.");
          projectActions.fetchProjects(state.form.projectId, false);
          return;
        }

        if (task.status === "failed") {
          dispatch({
            type: "PATCH_GRAPH_TASK",
            payload: {
              status: "error",
              message: task.error ?? task.message ?? "Graph build failed",
              taskId: "",
            },
          });
          addSystemLog(`Graph build failed: ${task.error ?? "Unknown error"}`);
          projectActions.fetchProjects(state.form.projectId, false);
          return;
        }

        dispatch({
          type: "PATCH_GRAPH_TASK",
          payload: {
            status: "running",
            message: task.message ?? "Building graph...",
            progress: task.progress ?? 0,
          },
        });
      } catch (error) {
        if (cancelled) return;
        graphPollErrorCount += 1;
        const errorText = String(error);
        if (graphPollErrorCount < MAX_TASK_POLL_ERROR_RETRIES) {
          addSystemLog(
            `Polling graph task failed (${graphPollErrorCount}/${MAX_TASK_POLL_ERROR_RETRIES}), retrying: ${errorText}`,
          );
          return;
        }
        addSystemLog(
          `Exception in pollTaskStatus after ${MAX_TASK_POLL_ERROR_RETRIES} retries: ${errorText}`,
        );
        dispatch({
          type: "PATCH_GRAPH_TASK",
          payload: {
            status: "error",
            message: errorText,
            taskId: "",
          },
        });
      }
    };

    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [state.graphTask.taskId]);

  const value = {
    state,
    setViewMode,
    refreshGraphFrame,
    setFormField,
    fetchPromptLabels: promptLabelActions.fetchPromptLabels,
    createPromptLabel: promptLabelActions.createPromptLabel,
    deletePromptLabel: promptLabelActions.deletePromptLabel,
    syncPromptLabelFromLangfuse: promptLabelActions.syncPromptLabelFromLangfuse,
    generatePromptLabelTypeListsFromLlm: promptLabelActions.generatePromptLabelTypeListsFromLlm,
    createDraftProject: promptLabelActions.createDraftProject,
    getPromptLabelTypeLists: promptLabelActions.getPromptLabelTypeLists,
    getPromptLabelPromptTemplate: promptLabelActions.getPromptLabelPromptTemplate,
    updatePromptLabelPromptTemplate: promptLabelActions.updatePromptLabelPromptTemplate,
    syncPromptLabelPromptTemplateFromDefault:
      promptLabelActions.syncPromptLabelPromptTemplateFromDefault,
    updatePromptLabelTypeLists: promptLabelActions.updatePromptLabelTypeLists,
    setProjectPromptLabel: projectActions.setProjectPromptLabel,
    setFiles,
    switchProject: projectActions.switchProject,
    fetchProjects: projectActions.fetchProjects,
    refreshProjects: projectActions.refreshProjects,
    updateProjectName: projectActions.updateProjectName,
    updateProjectOntologyTypes: projectActions.updateProjectOntologyTypes,
    deleteProject: projectActions.deleteProject,
    checkBackendHealth: healthActions.checkBackendHealth,
    runOntologyGenerate: ontologyActions.runOntologyGenerate,
    runGraphBuild: graphActions.runGraphBuild,
    addSystemLog,
  };

  return <TaskStoreContext.Provider value={value}>{children}</TaskStoreContext.Provider>;
}

export function useTaskStore() {
  const context = useContext(TaskStoreContext);
  if (!context) {
    throw new Error("useTaskStore must be used inside TaskStoreProvider");
  }
  return context;
}
