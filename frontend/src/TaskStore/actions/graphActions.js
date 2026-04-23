import {
  normalizeNonNegativeInteger,
  normalizePositiveInteger,
  normalizeProjectId,
} from "../utils";

function createGraphActions({
  state,
  dispatch,
  addSystemLog,
  withApiBase,
  trackedFetch,
  seenGraphLatencyEventIdsRef,
  lastGraphTaskMessageRef,
  fetchProjects,
}) {
  const toOptionalPositiveInteger = (value) => {
    const parsed = Number.parseInt(String(value ?? "").trim(), 10);
    if (!Number.isFinite(parsed) || parsed <= 0) return undefined;
    return parsed;
  };

  const runGraphBuild = async () => {
    const {
      projectId,
      graphName,
      graphLabel,
      chunkSize,
      chunkOverlap,
      chunkMode,
      overrideGraph,
      enableOtelTracing,
      enableOracleRuntimeOverrides,
      oraclePoolMin,
      oraclePoolMax,
      oraclePoolIncrement,
      oracleMaxCoroutines,
      useProjectNameAsGraphId,
      graphBackend,
      graphitiEmbeddingModel,
    } = state.form;
    const existingGraphId = String(
      state.currentProject?.zep_graph_id ?? state.currentProject?.graph_id ?? "",
    ).trim();
    const useProjectNameGraphId = Boolean(useProjectNameAsGraphId);
    const effectiveGraphId = useProjectNameGraphId ? "" : existingGraphId;
    if (!normalizeProjectId(projectId)) {
      addSystemLog("Validation failed: project_id is required.");
      dispatch({
        type: "PATCH_GRAPH_TASK",
        payload: {
          status: "error",
          message: "Project ID is required",
        },
      });
      return;
    }

    dispatch({
      type: "PATCH_GRAPH_TASK",
      payload: {
        status: "running",
        message: "Starting graph build...",
        progress: 0,
        startedAt: new Date().toISOString(),
        nodeCount: 0,
        edgeCount: 0,
        chunkCount: 0,
      },
    });
    dispatch({ type: "SET_GRAPH_RESUME_CANDIDATE", payload: null });
    seenGraphLatencyEventIdsRef.current = new Set();
    const resolvedGraphName = String(graphName ?? "").trim() || projectId;
    const resolvedGraphLabel = String(graphLabel ?? "").trim();
    const resolvedChunkMode = String(chunkMode ?? "fixed").trim().toLowerCase() || "fixed";
    const usesLlamaIndexChunking = resolvedChunkMode === "llama_index";
    const resolvedChunkSize = usesLlamaIndexChunking
      ? -1
      : normalizePositiveInteger(chunkSize, 500);
    const fallbackOverlap = normalizeNonNegativeInteger(chunkOverlap, 50);
    const resolvedChunkOverlap = usesLlamaIndexChunking
      ? -1
      : Math.min(fallbackOverlap, Math.max(resolvedChunkSize - 1, 0));
    const resolvedOverrideGraph = Boolean(overrideGraph);
    const resolvedEnableOtelTracing = Boolean(enableOtelTracing);
    const resolvedGraphBackendForRequest =
      String(graphBackend ?? "").trim() || state.currentProject?.graph_backend || "";
    const resolvedGraphitiEmbeddingModelForRequest =
      String(graphitiEmbeddingModel ?? "").trim() ||
      state.currentProject?.graphiti_embedding_model ||
      state.backendHealth?.graphitiDefaultEmbeddingModel ||
      "text-embedding-3-large";
    const resolvedOraclePoolMin = toOptionalPositiveInteger(oraclePoolMin);
    const resolvedOraclePoolMax = toOptionalPositiveInteger(oraclePoolMax);
    const resolvedOraclePoolIncrement = toOptionalPositiveInteger(oraclePoolIncrement);
    const resolvedOracleMaxCoroutines = toOptionalPositiveInteger(oracleMaxCoroutines);
    const isOracleBackend = String(resolvedGraphBackendForRequest ?? "").trim().toLowerCase() === "oracle";
    const resolvedEnableOracleRuntimeOverrides = Boolean(enableOracleRuntimeOverrides);
    const graphModeLabel = useProjectNameGraphId
      ? "project name as graph_id (zep_cloud)"
      : effectiveGraphId
        ? `existing graph_id: ${effectiveGraphId}`
        : "new graph";
    addSystemLog(
      `Starting graph build for ${projectId} (${graphModeLabel}, backend: ${resolvedGraphBackendForRequest || "auto"}, graphiti_embedding_model: ${resolvedGraphitiEmbeddingModelForRequest}, graph name: ${resolvedGraphName}, graph label: ${resolvedGraphLabel || "-"}, chunk_mode: ${resolvedChunkMode}, chunk_size: ${resolvedChunkSize}, chunk_overlap: ${resolvedChunkOverlap}, override: ${resolvedOverrideGraph ? "on" : "off"}, otel tracing: ${resolvedEnableOtelTracing ? "on" : "off"}${isOracleBackend ? `, oracle_runtime_overrides: ${resolvedEnableOracleRuntimeOverrides ? "on" : "off"}, oracle_pool(min/max/inc): ${resolvedOraclePoolMin ?? "-"} / ${resolvedOraclePoolMax ?? "-"} / ${resolvedOraclePoolIncrement ?? "-"}, oracle_max_coroutines: ${resolvedOracleMaxCoroutines ?? "-"}` : ""})...`,
    );

    try {
      const response = await trackedFetch(
        withApiBase("/api/build"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            graph_id: effectiveGraphId || undefined,
            graph_backend: resolvedGraphBackendForRequest || undefined,
            graph_name: resolvedGraphName,
            graph_label: resolvedGraphLabel || undefined,
            chunk_mode: resolvedChunkMode,
            chunk_size: resolvedChunkSize,
            chunk_overlap: resolvedChunkOverlap,
            graphiti_embedding_model: resolvedGraphitiEmbeddingModelForRequest,
            override: resolvedOverrideGraph,
            enable_otel_tracing: resolvedEnableOtelTracing,
            enable_oracle_runtime_overrides: isOracleBackend
              ? resolvedEnableOracleRuntimeOverrides
              : undefined,
            oracle_pool_min:
              isOracleBackend && resolvedEnableOracleRuntimeOverrides
                ? resolvedOraclePoolMin
                : undefined,
            oracle_pool_max:
              isOracleBackend && resolvedEnableOracleRuntimeOverrides
                ? resolvedOraclePoolMax
                : undefined,
            oracle_pool_increment:
              isOracleBackend && resolvedEnableOracleRuntimeOverrides
                ? resolvedOraclePoolIncrement
                : undefined,
            oracle_max_coroutines:
              isOracleBackend && resolvedEnableOracleRuntimeOverrides
                ? resolvedOracleMaxCoroutines
                : undefined,
            use_project_name_as_graph_id: useProjectNameGraphId,
          }),
        },
        { source: "api" },
      );
      const payload = await response.json();

      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error ?? "Graph build request failed");
      }

      const newTaskId = String(payload?.data?.task_id ?? "").trim();
      dispatch({
        type: "PATCH_GRAPH_TASK",
        payload: {
          status: "running",
          message: payload?.data?.message ?? "Graph build submitted",
          taskId: newTaskId,
          startedAt: new Date().toISOString(),
        },
      });
      const submittedMessage = payload?.data?.message ?? "Graph build submitted";
      lastGraphTaskMessageRef.current = submittedMessage;
      addSystemLog(submittedMessage);
      if (newTaskId) {
        addSystemLog(`New graph build task_id: ${newTaskId} (project: ${projectId}).`);
      }
      await fetchProjects(projectId, false);
    } catch (error) {
      addSystemLog(`Exception in buildGraph: ${String(error)}`);
      dispatch({
        type: "PATCH_GRAPH_TASK",
        payload: {
          status: "error",
          message: String(error),
          taskId: "",
          startedAt: "",
        },
      });
    }
  };

  const cancelGraphBuild = async () => {
    const taskId = String(state.graphTask?.taskId ?? "").trim();
    if (!taskId) {
      addSystemLog("No running Step B task to cancel.");
      return;
    }
    addSystemLog(`Cancelling graph build task ${taskId}...`);
    try {
      const response = await trackedFetch(
        withApiBase(`/api/task/${taskId}/cancel`),
        {
          method: "POST",
        },
        { source: "api" },
      );
      const payload = await response.json();
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error ?? "Failed to cancel graph build task");
      }
      dispatch({
        type: "PATCH_GRAPH_TASK",
        payload: {
          status: "idle",
          message: "Graph build cancelled",
          taskId: "",
          startedAt: "",
          progress: 0,
        },
      });
      addSystemLog(payload?.message ?? `Cancelled graph build task ${taskId}.`);
      await fetchProjects(state.form.projectId, false);
    } catch (error) {
      addSystemLog(`Failed to cancel graph build task: ${String(error)}`);
      dispatch({
        type: "PATCH_GRAPH_TASK",
        payload: {
          status: "error",
          message: String(error),
          startedAt: "",
        },
      });
    }
  };

  return { runGraphBuild, cancelGraphBuild };
}

export { createGraphActions };
