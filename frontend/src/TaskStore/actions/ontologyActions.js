import { getPreferredPromptLabel, normalizeProjectId } from "../utils";

function createOntologyActions({
  state,
  dispatch,
  addSystemLog,
  withApiBase,
  seenOntologyLatencyEventIdsRef,
  lastOntologyTaskMessageRef,
}) {
  const runOntologyGenerate = async () => {
    const { projectId, simulationRequirement, files, projectName, additionalContext, promptLabel } =
      state.form;
    const normalizedProjectId = normalizeProjectId(projectId);

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
      formData.append(
        "prompt_label",
        getPreferredPromptLabel(state.promptLabelCatalog.items, promptLabel),
      );

      const response = await fetch(withApiBase("/api/ontology/generate"), {
        method: "POST",
        body: formData,
      });
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

  return { runOntologyGenerate };
}

export { createOntologyActions };
