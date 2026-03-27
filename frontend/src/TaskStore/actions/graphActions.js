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
  seenGraphLatencyEventIdsRef,
  lastGraphTaskMessageRef,
  fetchProjects,
}) {
  const runGraphBuild = async () => {
    const { projectId, graphName, chunkSize, chunkOverlap } = state.form;
    const existingGraphId = String(
      state.currentProject?.zep_graph_id ?? state.currentProject?.graph_id ?? "",
    ).trim();
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
        nodeCount: 0,
        edgeCount: 0,
        chunkCount: 0,
      },
    });
    seenGraphLatencyEventIdsRef.current = new Set();
    const resolvedGraphName = String(graphName ?? "").trim() || projectId;
    const resolvedChunkSize = normalizePositiveInteger(chunkSize, 500);
    const fallbackOverlap = normalizeNonNegativeInteger(chunkOverlap, 50);
    const resolvedChunkOverlap = Math.min(fallbackOverlap, Math.max(resolvedChunkSize - 1, 0));
    const graphModeLabel = existingGraphId ? `existing graph_id: ${existingGraphId}` : "new graph";
    addSystemLog(
      `Starting graph build for ${projectId} (${graphModeLabel}, graph name: ${resolvedGraphName}, chunk_size: ${resolvedChunkSize}, chunk_overlap: ${resolvedChunkOverlap})...`,
    );

    try {
      const response = await fetch(withApiBase("/api/build"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          graph_id: existingGraphId || undefined,
          graph_name: resolvedGraphName,
          chunk_size: resolvedChunkSize,
          chunk_overlap: resolvedChunkOverlap,
        }),
      });
      const payload = await response.json();

      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error ?? "Graph build request failed");
      }

      dispatch({
        type: "PATCH_GRAPH_TASK",
        payload: {
          status: "running",
          message: payload?.data?.message ?? "Graph build submitted",
          taskId: payload?.data?.task_id ?? "",
        },
      });
      const submittedMessage = payload?.data?.message ?? "Graph build submitted";
      lastGraphTaskMessageRef.current = submittedMessage;
      addSystemLog(submittedMessage);
      await fetchProjects(projectId, false);
    } catch (error) {
      addSystemLog(`Exception in buildGraph: ${String(error)}`);
      dispatch({
        type: "PATCH_GRAPH_TASK",
        payload: {
          status: "error",
          message: String(error),
          taskId: "",
        },
      });
    }
  };

  return { runGraphBuild };
}

export { createGraphActions };
