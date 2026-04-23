import { createContext, useCallback, useContext, useEffect, useReducer, useRef } from "react";

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
const DEFAULT_TASK_POLL_INTERVAL_MS = 2000;
const MIN_TASK_POLL_INTERVAL_MS = 500;
const NETWORK_POPUP_SHOW_DELAY_MS = 180;
const NETWORK_POPUP_MIN_VISIBLE_MS = 320;

function normalizeMultilineMessage(value) {
  return String(value ?? "")
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t");
}

export function TaskStoreProvider({ children }) {
  const [state, dispatch] = useReducer(taskReducer, initialState);
  const taskPollIntervalMs = Math.max(
    MIN_TASK_POLL_INTERVAL_MS,
    Number(state.backendHealth?.taskPollIntervalMs ?? DEFAULT_TASK_POLL_INTERVAL_MS) ||
      DEFAULT_TASK_POLL_INTERVAL_MS,
  );
  const lastOntologyTaskMessageRef = useRef("");
  const lastGraphTaskMessageRef = useRef("");
  const seenOntologyLatencyEventIdsRef = useRef(new Set());
  const seenGraphLatencyEventIdsRef = useRef(new Set());
  const seenGraphResumeLogTaskIdsRef = useRef(new Set());
  const networkPopupShowTimerRef = useRef(null);
  const networkPopupHideTimerRef = useRef(null);
  const networkPopupVisibleSinceRef = useRef(0);
  const storeStateRef = useRef(state);
  useEffect(() => {
    storeStateRef.current = state;
  }, [state]);

  const reportLiveGraphBuildCounts = useCallback((nodeCount, edgeCount) => {
    if (storeStateRef.current.graphTask.status !== "running") return;
    dispatch({
      type: "PATCH_GRAPH_TASK",
      payload: {
        nodeCount: Number(nodeCount) || 0,
        edgeCount: Number(edgeCount) || 0,
      },
    });
  }, []);

  const addSystemLog = (message) => {
    if (!message) return;
    dispatch({ type: "ADD_SYSTEM_LOG", payload: normalizeMultilineMessage(message) });
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

  const trackedFetch = useCallback(async (input, init = undefined, options = {}) => {
    const track = options?.track !== false;
    const source = String(options?.source ?? "api").trim().toLowerCase();
    const shouldTrack =
      track && source !== "health" && source !== "task_polling" && source !== "graph_data_polling";
    if (shouldTrack) {
      dispatch({ type: "NETWORK_REQUEST_STARTED" });
    }
    try {
      return await fetch(input, init);
    } finally {
      if (shouldTrack) {
        dispatch({ type: "NETWORK_REQUEST_FINISHED" });
      }
    }
  }, []);

  const promptLabelActions = createPromptLabelActions({
    state,
    dispatch,
    addSystemLog,
    setFormField,
    withApiBase,
    trackedFetch,
  });

  const projectActions = createProjectActions({
    state,
    dispatch,
    addSystemLog,
    setFormField,
    setFormFields,
    withApiBase,
    trackedFetch,
    lastOntologyTaskMessageRef,
    lastGraphTaskMessageRef,
    seenOntologyLatencyEventIdsRef,
    seenGraphLatencyEventIdsRef,
  });

  const healthActions = createHealthActions({
    dispatch,
    addSystemLog,
    withApiBase,
    trackedFetch,
  });

  const ontologyActions = createOntologyActions({
    state,
    dispatch,
    addSystemLog,
    withApiBase,
    trackedFetch,
    seenOntologyLatencyEventIdsRef,
    lastOntologyTaskMessageRef,
  });

  const graphActions = createGraphActions({
    state,
    dispatch,
    addSystemLog,
    withApiBase,
    trackedFetch,
    seenGraphLatencyEventIdsRef,
    lastGraphTaskMessageRef,
    fetchProjects: projectActions.fetchProjects,
  });

  useEffect(() => {
    addSystemLog("Project view initialized.");
    healthActions.checkBackendHealth();
    promptLabelActions.fetchPromptLabels({ syncFormLabel: true }).then(() => {
      projectActions.fetchProjects(undefined, false);
    });
    const timer = setInterval(healthActions.checkBackendHealth, 30000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const pendingCount = Math.max(0, Number(state.networkActivity?.pendingCount ?? 0));
    const visible = Boolean(state.networkActivity?.visible);

    if (pendingCount > 0) {
      if (!visible && !networkPopupShowTimerRef.current) {
        networkPopupShowTimerRef.current = setTimeout(() => {
          networkPopupShowTimerRef.current = null;
          if (Math.max(0, Number(storeStateRef.current.networkActivity?.pendingCount ?? 0)) > 0) {
            networkPopupVisibleSinceRef.current = Date.now();
            dispatch({ type: "SET_NETWORK_ACTIVITY_VISIBLE", payload: true });
          }
        }, NETWORK_POPUP_SHOW_DELAY_MS);
      }
      if (networkPopupHideTimerRef.current) {
        clearTimeout(networkPopupHideTimerRef.current);
        networkPopupHideTimerRef.current = null;
      }
      return;
    }

    if (networkPopupShowTimerRef.current) {
      clearTimeout(networkPopupShowTimerRef.current);
      networkPopupShowTimerRef.current = null;
    }
    if (!visible) {
      return;
    }
    const elapsedVisible = Date.now() - Number(networkPopupVisibleSinceRef.current || 0);
    const remainingVisible = Math.max(0, NETWORK_POPUP_MIN_VISIBLE_MS - elapsedVisible);
    if (networkPopupHideTimerRef.current) {
      clearTimeout(networkPopupHideTimerRef.current);
      networkPopupHideTimerRef.current = null;
    }
    networkPopupHideTimerRef.current = setTimeout(() => {
      networkPopupHideTimerRef.current = null;
      if (Math.max(0, Number(storeStateRef.current.networkActivity?.pendingCount ?? 0)) === 0) {
        dispatch({ type: "SET_NETWORK_ACTIVITY_VISIBLE", payload: false });
      }
    }, remainingVisible);
  }, [state.networkActivity?.pendingCount, state.networkActivity?.visible]);

  useEffect(() => {
    return () => {
      if (networkPopupShowTimerRef.current) {
        clearTimeout(networkPopupShowTimerRef.current);
        networkPopupShowTimerRef.current = null;
      }
      if (networkPopupHideTimerRef.current) {
        clearTimeout(networkPopupHideTimerRef.current);
        networkPopupHideTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!state.ontologyTask.taskId) return undefined;

    let cancelled = false;
    const { taskId } = state.ontologyTask;
    let ontologyPollErrorCount = 0;
    addSystemLog(`Polling ontology task ${taskId}...`);

    const poll = async () => {
      try {
        const response = await trackedFetch(withApiBase(`/api/task/${taskId}`), undefined, {
          source: "task_polling",
        });
        const payload = await response.json();
        if (!response.ok || !payload?.success) {
          throw new Error(payload?.error ?? "Ontology task polling failed");
        }

        const task = payload.data;
        if (cancelled) return;
        ontologyPollErrorCount = 0;
        appendTaskLatencyLogs(task, seenOntologyLatencyEventIdsRef, "Step A");

        const taskMessage = normalizeMultilineMessage(task.message);
        const taskError = normalizeMultilineMessage(task.error);

        if (taskMessage && taskMessage !== lastOntologyTaskMessageRef.current) {
          lastOntologyTaskMessageRef.current = taskMessage;
          addSystemLog(taskMessage);
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
                taskMessage ??
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
              message: taskError || taskMessage || "Ontology generation failed",
              taskId: "",
              progress: 100,
              startedAt: "",
            },
          });
          addSystemLog(`Ontology generation failed:\n${taskError || "Unknown error"}`);
          return;
        }

        if (task.status === "cancelled") {
          dispatch({
            type: "PATCH_ONTOLOGY_TASK",
            payload: {
              status: "idle",
              message: taskMessage || "Ontology generation cancelled",
              taskId: "",
              progress: 0,
              startedAt: "",
            },
          });
          addSystemLog(taskMessage || "Ontology generation cancelled.");
          return;
        }

        dispatch({
          type: "PATCH_ONTOLOGY_TASK",
          payload: {
            status: "running",
            message: taskMessage || "Generating ontology...",
            progress: task.progress ?? 0,
            startedAt: String(task?.created_at ?? "").trim(),
          },
        });
      } catch (error) {
        if (cancelled) return;
        ontologyPollErrorCount += 1;
        const errorText = normalizeMultilineMessage(error);
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
    const timer = setInterval(poll, taskPollIntervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [state.ontologyTask.taskId, taskPollIntervalMs, trackedFetch]);

  useEffect(() => {
    if (!state.graphTask.taskId) return undefined;

    let cancelled = false;
    const { taskId } = state.graphTask;
    let graphPollErrorCount = 0;
    addSystemLog(`Polling task ${taskId}...`);

    const poll = async () => {
      try {
        const response = await trackedFetch(withApiBase(`/api/task/${taskId}`), undefined, {
          source: "task_polling",
        });
        const payload = await response.json();
        if (!response.ok || !payload?.success) {
          throw new Error(payload?.error ?? "Task polling failed");
        }

        const task = payload.data;
        if (cancelled) return;
        graphPollErrorCount = 0;
        appendTaskLatencyLogs(task, seenGraphLatencyEventIdsRef, "Step B");
        const pd =
          task?.progress_detail && typeof task.progress_detail === "object"
            ? task.progress_detail
            : {};
        const resumeState = String(pd.resume_state ?? "").trim().toLowerCase();
        if (
          resumeState === "resuming" &&
          !seenGraphResumeLogTaskIdsRef.current.has(taskId)
        ) {
          seenGraphResumeLogTaskIdsRef.current.add(taskId);
          const matchedPrev = String(pd.matched_task_id ?? "").trim() || "unknown";
          const totalBatches =
            pd.total_batches !== undefined && pd.total_batches !== null
              ? String(pd.total_batches)
              : "?";
          const lastDone = pd.last_completed_batch_index;
          const startBatch =
            typeof lastDone === "number" && Number.isFinite(lastDone)
              ? String(lastDone + 1)
              : "?";
          addSystemLog(
            `[Step B] Resuming graph build from previous task_id=${matchedPrev}; starting at batch ${startBatch}/${totalBatches}.`,
          );
        }
        const taskMessage = normalizeMultilineMessage(task.message);
        const taskError = normalizeMultilineMessage(task.error);

        const liveGraphId = String(pd.zep_graph_id ?? pd.graph_id ?? "").trim();
        const liveWorkspaceId = String(pd.project_workspace_id ?? "").trim();
        const liveAddress = String(pd.zep_graph_address ?? "").trim();
        const liveBackend = String(pd.graph_backend ?? "").trim();
        const liveEmbeddingModel = String(pd.graphiti_embedding_model ?? "").trim();
        if (liveGraphId && storeStateRef.current.currentProject) {
          const patch = {
            zep_graph_id: liveGraphId,
            graph_id: liveGraphId,
            ...(liveWorkspaceId ? { project_workspace_id: liveWorkspaceId } : {}),
            ...(liveAddress ? { zep_graph_address: liveAddress } : {}),
            ...(liveBackend ? { graph_backend: liveBackend } : {}),
            ...(liveEmbeddingModel ? { graphiti_embedding_model: liveEmbeddingModel } : {}),
          };
          const cur = storeStateRef.current.currentProject;
          const needsPatch =
            String(cur.zep_graph_id ?? cur.graph_id ?? "").trim() !== liveGraphId ||
            (liveWorkspaceId &&
              String(cur.project_workspace_id ?? "").trim() !== liveWorkspaceId) ||
            (liveAddress && String(cur.zep_graph_address ?? "").trim() !== liveAddress) ||
            (liveBackend && String(cur.graph_backend ?? "").trim() !== liveBackend) ||
            (liveEmbeddingModel &&
              String(cur.graphiti_embedding_model ?? "").trim() !== liveEmbeddingModel);
          if (needsPatch) {
            dispatch({ type: "PATCH_CURRENT_PROJECT", payload: patch });
          }
        }

        if (taskMessage && taskMessage !== lastGraphTaskMessageRef.current) {
          lastGraphTaskMessageRef.current = taskMessage;
          addSystemLog(taskMessage);
        }

        if (task.status === "completed") {
          const completedGraphId = task.result?.zep_graph_id ?? task.result?.graph_id ?? "";
          dispatch({
            type: "PATCH_GRAPH_TASK",
            payload: {
              status: "success",
              message: taskMessage || "Graph build completed",
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
                graphiti_embedding_model:
                  task.result?.graphiti_embedding_model ??
                  state.currentProject?.graphiti_embedding_model ??
                  "",
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
              message: taskError || taskMessage || "Graph build failed",
              taskId: "",
              startedAt: "",
            },
          });
          addSystemLog(`Graph build failed:\n${taskError || "Unknown error"}`);
          projectActions.fetchProjects(state.form.projectId, false);
          dispatch({
            type: "SET_GRAPH_RESUME_CANDIDATE",
            payload: {
              taskId: String(task?.task_id ?? taskId ?? "").trim(),
              status: "failed",
              totalBatches:
                typeof pd.total_batches === "number" && Number.isFinite(pd.total_batches)
                  ? pd.total_batches
                  : null,
              lastCompletedBatchIndex:
                typeof pd.last_completed_batch_index === "number" &&
                Number.isFinite(pd.last_completed_batch_index)
                  ? pd.last_completed_batch_index
                  : -1,
              batchSize:
                typeof pd.batch_size === "number" && Number.isFinite(pd.batch_size)
                  ? pd.batch_size
                  : null,
              resumeState: String(pd.resume_state ?? "").trim().toLowerCase() || "failed",
              updatedAt: String(task?.updated_at ?? "").trim(),
            },
          });
          return;
        }

        if (task.status === "cancelled") {
          dispatch({
            type: "PATCH_GRAPH_TASK",
            payload: {
              status: "idle",
              message: taskMessage || "Graph build cancelled",
              taskId: "",
              startedAt: "",
              progress: 0,
            },
          });
          addSystemLog(taskMessage || "Graph build cancelled.");
          projectActions.fetchProjects(state.form.projectId, false);
          dispatch({
            type: "SET_GRAPH_RESUME_CANDIDATE",
            payload: {
              taskId: String(task?.task_id ?? taskId ?? "").trim(),
              status: "cancelled",
              totalBatches:
                typeof pd.total_batches === "number" && Number.isFinite(pd.total_batches)
                  ? pd.total_batches
                  : null,
              lastCompletedBatchIndex:
                typeof pd.last_completed_batch_index === "number" &&
                Number.isFinite(pd.last_completed_batch_index)
                  ? pd.last_completed_batch_index
                  : -1,
              batchSize:
                typeof pd.batch_size === "number" && Number.isFinite(pd.batch_size)
                  ? pd.batch_size
                  : null,
              resumeState: String(pd.resume_state ?? "").trim().toLowerCase() || "cancelled",
              updatedAt: String(task?.updated_at ?? "").trim(),
            },
          });
          return;
        }

        dispatch({
          type: "PATCH_GRAPH_TASK",
          payload: {
            status: "running",
            message: taskMessage || "Building graph...",
            progress: task.progress ?? 0,
            startedAt: String(task?.created_at ?? "").trim(),
          },
        });
      } catch (error) {
        if (cancelled) return;
        graphPollErrorCount += 1;
        const errorText = normalizeMultilineMessage(error);
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
            startedAt: "",
          },
        });
      }
    };

    poll();
    const timer = setInterval(poll, taskPollIntervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [state.graphTask.taskId, taskPollIntervalMs, trackedFetch]);

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
    updateProjectRefreshDataWhileBuild: projectActions.updateProjectRefreshDataWhileBuild,
    updateProjectOntologyTypes: projectActions.updateProjectOntologyTypes,
    fetchProjectOntologyVersions: projectActions.fetchProjectOntologyVersions,
    mergeProjectOntology: projectActions.mergeProjectOntology,
    deleteProject: projectActions.deleteProject,
    checkBackendHealth: healthActions.checkBackendHealth,
    runOntologyGenerate: ontologyActions.runOntologyGenerate,
    cancelOntologyTask: ontologyActions.cancelOntologyTask,
    runGraphBuild: graphActions.runGraphBuild,
    cancelGraphBuild: graphActions.cancelGraphBuild,
    reportLiveGraphBuildCounts,
    addSystemLog,
    trackedFetch,
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
