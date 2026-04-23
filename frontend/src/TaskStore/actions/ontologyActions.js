import { getPreferredPromptLabel, normalizeProjectId } from "../utils";

function createOntologyActions({
  state,
  dispatch,
  addSystemLog,
  withApiBase,
  trackedFetch,
  seenOntologyLatencyEventIdsRef,
  lastOntologyTaskMessageRef,
}) {
  const normalizeMinimumCount = (value, fallback = 10) => {
    const parsed = Number.parseInt(String(value ?? ""), 10);
    if (!Number.isFinite(parsed) || parsed < 1) {
      return fallback;
    }
    return parsed;
  };
  const normalizePdfPage = (value, fallback) => {
    const parsed = Number.parseInt(String(value ?? ""), 10);
    if (!Number.isFinite(parsed) || parsed < 1) {
      return fallback;
    }
    return parsed;
  };

  const runOntologyGenerate = async () => {
    if (state.ontologyTask?.status === "running") {
      addSystemLog("Step A request is already in progress.");
      return;
    }
    const {
      projectId,
      simulationRequirement,
      files,
      projectName,
      additionalContext,
      promptLabel,
      minimumNodes,
      minimumEdges,
      graphBackend,
      usePdfPageRange,
      pdfPageFrom,
      pdfPageTo,
    } = state.form;
    const normalizedProjectId = normalizeProjectId(projectId);
    const normalizedMinimumNodes = normalizeMinimumCount(minimumNodes, 10);
    const normalizedMinimumEdges = normalizeMinimumCount(minimumEdges, 10);
    const normalizedPdfPageFrom = normalizePdfPage(pdfPageFrom, 1);
    const normalizedPdfPageTo = normalizePdfPage(pdfPageTo, 100);
    const resolvedPdfPageFrom = Math.min(normalizedPdfPageFrom, normalizedPdfPageTo);
    const resolvedPdfPageTo = Math.max(normalizedPdfPageFrom, normalizedPdfPageTo);

    if (!simulationRequirement.trim()) {
      addSystemLog("Validation failed: simulation requirement is required.");
      dispatch({
        type: "PATCH_ONTOLOGY_TASK",
        payload: {
          status: "error",
          message: "Simulation requirement is required",
        },
      });
      return;
    }

    if (!files.length) {
      addSystemLog("Validation failed: please upload at least one file.");
      dispatch({
        type: "PATCH_ONTOLOGY_TASK",
        payload: {
          status: "error",
          message: "Please upload at least one file",
        },
      });
      return;
    }

    dispatch({
      type: "PATCH_ONTOLOGY_TASK",
      payload: {
        status: "running",
        message: "Submitting ontology generation task...",
        progress: 0,
        taskId: "",
        startedAt: new Date().toISOString(),
        entityTypes: 0,
        edgeTypes: 0,
      },
    });
    seenOntologyLatencyEventIdsRef.current = new Set();
    addSystemLog(
      normalizedProjectId
        ? `Starting ontology generation (reuse project: ${normalizedProjectId})...`
        : "Starting ontology generation (new project)...",
    );

    try {
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file));
      if (normalizedProjectId) {
        formData.append("project_id", normalizedProjectId);
      }
      formData.append("simulation_requirement", simulationRequirement);
      formData.append("project_name", projectName);
      formData.append("additional_context", additionalContext);
      formData.append("minimum_nodes", String(normalizedMinimumNodes));
      formData.append("minimum_edges", String(normalizedMinimumEdges));
      if (Boolean(usePdfPageRange)) {
        formData.append("pdf_page_from", String(resolvedPdfPageFrom));
        formData.append("pdf_page_to", String(resolvedPdfPageTo));
      }
      formData.append("graph_backend", String(graphBackend ?? "").trim());
      formData.append(
        "prompt_label",
        getPreferredPromptLabel(state.promptLabelCatalog.items, promptLabel),
      );

      const response = await trackedFetch(
        withApiBase("/api/ontology/generate"),
        {
        method: "POST",
        body: formData,
        },
        { source: "api" },
      );
      const payload = await response.json();

      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error ?? "Ontology generation failed");
      }
      const submittedTaskId = String(payload?.data?.task_id ?? "").trim();
      if (!submittedTaskId) {
        throw new Error("Ontology generation task id is missing");
      }

      dispatch({
        type: "PATCH_ONTOLOGY_TASK",
        payload: {
          status: "running",
          message: payload?.data?.message ?? "Ontology task submitted",
          taskId: submittedTaskId,
          startedAt: new Date().toISOString(),
        },
      });
      lastOntologyTaskMessageRef.current = payload?.data?.message ?? "";
      addSystemLog(payload?.data?.message ?? "Ontology task submitted.");
    } catch (error) {
      addSystemLog(`Exception in generateOntology: ${String(error)}`);
      dispatch({
        type: "PATCH_ONTOLOGY_TASK",
        payload: { status: "error", message: String(error) },
      });
    }
  };

  const cancelOntologyTask = async () => {
    const taskId = String(state.ontologyTask?.taskId ?? "").trim();
    if (!taskId) {
      addSystemLog("No running Step A task to cancel.");
      return;
    }
    addSystemLog(`Cancelling ontology task ${taskId}...`);
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
        throw new Error(payload?.error ?? "Failed to cancel ontology task");
      }
      dispatch({
        type: "PATCH_ONTOLOGY_TASK",
        payload: {
          status: "idle",
          message: "Ontology generation cancelled",
          taskId: "",
          progress: 0,
          startedAt: "",
        },
      });
      addSystemLog(payload?.message ?? `Cancelled ontology task ${taskId}.`);
    } catch (error) {
      addSystemLog(`Failed to cancel ontology task: ${String(error)}`);
      dispatch({
        type: "PATCH_ONTOLOGY_TASK",
        payload: {
          status: "error",
          message: String(error),
        },
      });
    }
  };

  return { runOntologyGenerate, cancelOntologyTask };
}

export { createOntologyActions };
