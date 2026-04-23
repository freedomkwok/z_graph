import { readLastProjectId, rememberLastProjectId } from "../storage";
import {
  buildUpdatedOntologyFromDefinitions,
  buildUpdatedOntologyFromTypeNames,
  getPreferredPromptLabel,
  normalizeNonNegativeInteger,
  normalizePositiveInteger,
  normalizeProjectId,
  parseJsonResponse,
} from "../utils";
import { getGraphTaskFromProject, getOntologyTaskFromProject, initialGraphTask, initialOntologyTask } from "../state";

let projectListRequestInFlight = null;

/** Coalesce concurrent GET /api/project/:id (per id) into one HTTP request. */
const projectDetailInFlight = new Map();
/** After a fast response, React 18 Strict Mode may run the startup effect again; reuse briefly. */
const projectDetailLastOk = new Map();
const PROJECT_DETAIL_DEDUP_MS = 750;
const PROJECT_DETAIL_REQUEST_TIMEOUT_MS = 12000;

const toOptionalPositiveIntegerString = (value) => {
  const parsed = Number.parseInt(String(value ?? "").trim(), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return "";
  return String(parsed);
};

async function fetchProjectDetailPayload(
  withApiBase,
  trackedFetch,
  selectedProjectId,
  { skipDedup = false } = {},
) {
  if (skipDedup) {
    projectDetailLastOk.delete(selectedProjectId);
  }

  const now = Date.now();
  const lastOk = projectDetailLastOk.get(selectedProjectId);
  if (
    !skipDedup &&
    lastOk?.project &&
    now - (lastOk.completedAt ?? 0) < PROJECT_DETAIL_DEDUP_MS
  ) {
    return {
      fromCache: true,
      response: { ok: true },
      payload: { success: true, data: lastOk.project },
    };
  }

  if (!skipDedup && projectDetailInFlight.has(selectedProjectId)) {
    return projectDetailInFlight.get(selectedProjectId);
  }

  if (skipDedup && projectDetailInFlight.has(selectedProjectId)) {
    await projectDetailInFlight.get(selectedProjectId);
  }

  const run = (async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), PROJECT_DETAIL_REQUEST_TIMEOUT_MS);
    try {
      const response = await trackedFetch(
        withApiBase(`/api/project/${selectedProjectId}`),
        { signal: controller.signal },
        {
          source: "api",
        },
      );
      const payload = await response.json();
      const unified = { fromCache: false, response, payload };
      if (response.ok && payload?.success && payload?.data) {
        projectDetailLastOk.set(selectedProjectId, { project: payload.data, completedAt: Date.now() });
      }
      return unified;
    } catch (error) {
      if (controller.signal.aborted || String(error?.name ?? "") === "AbortError") {
        throw new Error(
          `Project ${selectedProjectId} loading timed out after ${Math.floor(PROJECT_DETAIL_REQUEST_TIMEOUT_MS / 1000)}s`,
        );
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  })();

  projectDetailInFlight.set(selectedProjectId, run);
  try {
    return await run;
  } finally {
    projectDetailInFlight.delete(selectedProjectId);
  }
}

async function fetchProjectListPayload(withApiBase, trackedFetch) {
  if (projectListRequestInFlight) {
    return projectListRequestInFlight;
  }

  projectListRequestInFlight = (async () => {
    const response = await trackedFetch(withApiBase("/api/project/list?limit=200"), undefined, {
      source: "api",
    });
    const payload = await response.json();
    return { response, payload };
  })();

  try {
    return await projectListRequestInFlight;
  } finally {
    projectListRequestInFlight = null;
  }
}

function createProjectActions({
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
}) {
  async function switchProject(projectId, preferredWorkspaceId = "", options = {}) {
    const selectedProjectId = (projectId ?? "").trim();
    const skipDedup = Boolean(options?.skipDedup);
    setFormField("projectId", selectedProjectId);
    rememberLastProjectId(selectedProjectId);

    if (!selectedProjectId) {
      dispatch({ type: "SET_ONTOLOGY_TASK", payload: initialOntologyTask });
      dispatch({ type: "SET_GRAPH_TASK", payload: initialGraphTask });
      dispatch({ type: "SET_CURRENT_PROJECT", payload: null });
      dispatch({ type: "SET_GRAPH_RESUME_CANDIDATE", payload: null });
      dispatch({ type: "SET_FILES", payload: [] });
      setFormFields({
        usePdfPageRange: false,
        pdfPageFrom: 1,
        pdfPageTo: 100,
        projectName: "New Project",
        simulationRequirement: "",
        additionalContext: "",
        promptLabel: getPreferredPromptLabel(state.promptLabelCatalog.items, "Production"),
        minimumNodes: 10,
        minimumEdges: 10,
        graphName: "",
        graphLabel: "",
        chunkSize: 500,
        chunkOverlap: 50,
        chunkMode: "fixed",
        overrideGraph: false,
        enableOtelTracing: Boolean(state.backendHealth?.graphitiTracingDefaultEnabled),
        enableOracleRuntimeOverrides: true,
        oraclePoolMin: "",
        oraclePoolMax: "",
        oraclePoolIncrement: "",
        oracleMaxCoroutines: "",
        refreshDataWhileBuild: true,
        refreshDataPollSeconds: 20,
        graphBackend: String(options?.graphBackend ?? state.form.graphBackend ?? "zep_cloud"),
        graphitiEmbeddingModel:
          String(
            state.form.graphitiEmbeddingModel ??
              state.backendHealth?.graphitiDefaultEmbeddingModel ??
              "text-embedding-3-large",
          ).trim() || "text-embedding-3-large",
        useProjectNameAsGraphId: false,
      });
      lastOntologyTaskMessageRef.current = "";
      lastGraphTaskMessageRef.current = "";
      seenOntologyLatencyEventIdsRef.current = new Set();
      seenGraphLatencyEventIdsRef.current = new Set();
      addSystemLog("Switched to New Project mode.");
      return;
    }

    addSystemLog(`Loading project ${selectedProjectId}...`);
    try {
      const { response, payload } = await fetchProjectDetailPayload(
        withApiBase,
        trackedFetch,
        selectedProjectId,
        {
        skipDedup,
        },
      );
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error ?? "Failed to load project");
      }

      const project = payload.data;
      const resolvedWorkspaceId =
        project?.project_workspace_id ?? project?.workspace_id ?? preferredWorkspaceId;
      const hydratedProject = resolvedWorkspaceId
        ? { ...project, project_workspace_id: resolvedWorkspaceId }
        : project;
      dispatch({ type: "SET_CURRENT_PROJECT", payload: hydratedProject });
      const resolvedEnableOtelTracing =
        typeof hydratedProject.enable_otel_tracing === "boolean"
          ? hydratedProject.enable_otel_tracing
          : Boolean(state.backendHealth?.graphitiTracingDefaultEnabled);
      setFormFields({
        usePdfPageRange: false,
        pdfPageFrom: 1,
        pdfPageTo: 100,
        projectId: hydratedProject.project_id ?? selectedProjectId,
        projectName: hydratedProject.name ?? "IMP Graph Project",
        simulationRequirement: hydratedProject.context_requirement ?? "",
        minimumNodes: normalizePositiveInteger(hydratedProject.minimum_nodes, 10),
        minimumEdges: normalizePositiveInteger(hydratedProject.minimum_edges, 10),
        graphName: "",
        graphLabel: "",
        chunkSize: normalizePositiveInteger(hydratedProject.chunk_size, 500),
        chunkOverlap: normalizeNonNegativeInteger(hydratedProject.chunk_overlap, 50),
        chunkMode: String(hydratedProject.chunk_mode ?? "fixed").trim().toLowerCase() || "fixed",
        overrideGraph: false,
        enableOtelTracing: resolvedEnableOtelTracing,
        enableOracleRuntimeOverrides:
          typeof hydratedProject.enable_oracle_runtime_overrides === "boolean"
            ? hydratedProject.enable_oracle_runtime_overrides
            : true,
        oraclePoolMin: toOptionalPositiveIntegerString(hydratedProject.oracle_pool_min),
        oraclePoolMax: toOptionalPositiveIntegerString(hydratedProject.oracle_pool_max),
        oraclePoolIncrement: toOptionalPositiveIntegerString(hydratedProject.oracle_pool_increment),
        oracleMaxCoroutines: toOptionalPositiveIntegerString(hydratedProject.oracle_max_coroutines),
        refreshDataWhileBuild:
          typeof hydratedProject.refresh_data_while_build === "boolean"
            ? hydratedProject.refresh_data_while_build
            : true,
        refreshDataPollSeconds: 20,
        graphBackend: String(hydratedProject.graph_backend ?? state.form.graphBackend ?? "zep_cloud"),
        graphitiEmbeddingModel:
          String(
            hydratedProject.graphiti_embedding_model ??
              state.form.graphitiEmbeddingModel ??
              state.backendHealth?.graphitiDefaultEmbeddingModel ??
              "text-embedding-3-large",
          ).trim() || "text-embedding-3-large",
        useProjectNameAsGraphId: false,
        promptLabel: getPreferredPromptLabel(
          state.promptLabelCatalog.items,
          hydratedProject.prompt_label || "Production",
        ),
      });

      dispatch({
        type: "SET_ONTOLOGY_TASK",
        payload: getOntologyTaskFromProject(hydratedProject),
      });

      let nextGraphTask = getGraphTaskFromProject(hydratedProject);
      const projectStatus = String(hydratedProject?.status ?? "").trim().toLowerCase();
      const explicitGraphId = String(
        hydratedProject?.zep_graph_id ?? hydratedProject?.graph_id ?? "",
      ).trim();
      const projectGraphId = explicitGraphId;
      if (projectStatus === "graph_completed" && projectGraphId) {
        // GraphEmbedPanel owns graph payload loading.
        // Avoid duplicate /api/data requests during project hydration.
        nextGraphTask = {
          ...nextGraphTask,
          nodeCount: 0,
          edgeCount: 0,
        };
      }

      dispatch({
        type: "SET_GRAPH_TASK",
        payload: nextGraphTask,
      });
      const resumeCandidate = hydratedProject?.graph_resume_candidate;
      dispatch({
        type: "SET_GRAPH_RESUME_CANDIDATE",
        payload:
          resumeCandidate && typeof resumeCandidate === "object"
            ? {
                taskId: String(resumeCandidate.task_id ?? "").trim(),
                status: String(resumeCandidate.status ?? "").trim().toLowerCase(),
                totalBatches:
                  typeof resumeCandidate.total_batches === "number" &&
                  Number.isFinite(resumeCandidate.total_batches)
                    ? resumeCandidate.total_batches
                    : null,
                lastCompletedBatchIndex:
                  typeof resumeCandidate.last_completed_batch_index === "number" &&
                  Number.isFinite(resumeCandidate.last_completed_batch_index)
                    ? resumeCandidate.last_completed_batch_index
                    : -1,
                batchSize:
                  typeof resumeCandidate.batch_size === "number" &&
                  Number.isFinite(resumeCandidate.batch_size)
                    ? resumeCandidate.batch_size
                    : null,
                resumeState: String(resumeCandidate.resume_state ?? "").trim().toLowerCase(),
                updatedAt: String(resumeCandidate.updated_at ?? "").trim(),
              }
            : null,
      });
      lastOntologyTaskMessageRef.current = "";
      lastGraphTaskMessageRef.current = "";
      seenOntologyLatencyEventIdsRef.current = new Set();
      seenGraphLatencyEventIdsRef.current = new Set();
      addSystemLog(
        `Project loaded: ${hydratedProject.project_id} (${hydratedProject.status ?? "unknown status"})`,
      );
    } catch (error) {
      addSystemLog(`Exception in LoadProject: ${String(error)}`);
      dispatch({
        type: "PATCH_GRAPH_TASK",
        payload: {
          status: "error",
          message: `Failed to load project: ${String(error)}`,
          taskId: "",
        },
      });
    }
  }

  async function fetchProjects(preferredProjectId = state.form.projectId, hydrateSelection = true) {
    dispatch({
      type: "PATCH_PROJECT_CATALOG",
      payload: { loading: true, error: "" },
    });
    try {
      const { response, payload } = await fetchProjectListPayload(withApiBase, trackedFetch);
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error ?? "Failed to list projects");
      }

      const projects = Array.isArray(payload?.data) ? payload.data : [];
      dispatch({
        type: "SET_PROJECT_CATALOG",
        payload: { loading: false, error: "", items: projects },
      });

      if (projects.length === 0) {
        addSystemLog("No projects found.");
      }

      if (!hydrateSelection) return projects;

      const requested = preferredProjectId ?? "";
      const selectedFromState = state.form.projectId ?? "";
      const rememberedProjectId = readLastProjectId();
      const hasRequested = requested && projects.some((p) => p.project_id === requested);
      const hasSelected = selectedFromState && projects.some((p) => p.project_id === selectedFromState);
      const hasRemembered =
        rememberedProjectId && projects.some((p) => p.project_id === rememberedProjectId);

      let nextProjectId = "";
      if (hasRequested) {
        nextProjectId = requested;
      } else if (hasSelected) {
        nextProjectId = selectedFromState;
      } else if (hasRemembered) {
        nextProjectId = rememberedProjectId;
      } else if (projects.length > 0) {
        nextProjectId = projects[0].project_id;
      }

      if (nextProjectId) {
        await switchProject(nextProjectId);
      } else {
        rememberLastProjectId("");
      }
      return projects;
    } catch (error) {
      addSystemLog(`Exception in listProjects: ${String(error)}`);
      dispatch({
        type: "PATCH_PROJECT_CATALOG",
        payload: { loading: false, error: String(error) },
      });
      return [];
    }
  }

  const refreshProjects = async () => {
    addSystemLog("Refreshing project list...");
    await fetchProjects(state.form.projectId, false);
  };

  const updateProjectName = async (projectId, name) => {
    const normalizedProjectId = normalizeProjectId(projectId);
    const normalizedName = String(name ?? "").trim();
    if (!normalizedProjectId) {
      throw new Error("project_id is required");
    }
    if (!normalizedName) {
      throw new Error("Project name is required");
    }

    addSystemLog(`Updating project name for ${normalizedProjectId}...`);
    const response = await trackedFetch(
      withApiBase(`/api/project/${normalizedProjectId}`),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: normalizedName }),
      },
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to update project name");
    }

    const updatedProject = payload?.data;
    if (updatedProject?.project_id === state.form.projectId) {
      setFormField("projectName", updatedProject?.name ?? normalizedName);
    }
    await fetchProjects(state.form.projectId, false);
    addSystemLog(`Project updated: ${normalizedProjectId}`);
    return updatedProject;
  };

  const deleteProject = async (projectId) => {
    const normalizedProjectId = normalizeProjectId(projectId);
    if (!normalizedProjectId) {
      throw new Error("project_id is required");
    }

    addSystemLog(`Deleting project ${normalizedProjectId}...`);
    const response = await trackedFetch(
      withApiBase(`/api/project/${normalizedProjectId}`),
      {
        method: "DELETE",
      },
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to delete project");
    }

    if (normalizedProjectId === state.form.projectId) {
      await switchProject("");
    }
    await fetchProjects(undefined, true);
    addSystemLog(`Project deleted: ${normalizedProjectId}`);
    return true;
  };

  const updateProjectRefreshDataWhileBuild = async (projectId, enabled) => {
    const normalizedProjectId = normalizeProjectId(projectId);
    if (!normalizedProjectId) {
      throw new Error("project_id is required");
    }
    const resolvedEnabled = Boolean(enabled);
    const response = await trackedFetch(
      withApiBase(`/api/project/${normalizedProjectId}`),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_data_while_build: resolvedEnabled }),
      },
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to update refresh_data_while_build");
    }
    const updatedProject = payload?.data;
    if (updatedProject && normalizeProjectId(updatedProject.project_id) === state.form.projectId) {
      dispatch({ type: "SET_CURRENT_PROJECT", payload: updatedProject });
      dispatch({
        type: "SET_FORM_FIELD",
        field: "refreshDataWhileBuild",
        value:
          typeof updatedProject.refresh_data_while_build === "boolean"
            ? updatedProject.refresh_data_while_build
            : resolvedEnabled,
      });
    }
    return updatedProject;
  };

  const setProjectPromptLabel = async (label, options = {}) => {
    const forceExact = Boolean(options?.forceExact);
    const normalizedInput = String(label ?? "").trim() || "Production";
    const normalizedLabel = forceExact
      ? normalizedInput
      : getPreferredPromptLabel(state.promptLabelCatalog.items, normalizedInput);
    setFormField("promptLabel", normalizedLabel);
    const projectId = normalizeProjectId(state.form.projectId);
    if (!projectId) return;

    try {
      const response = await trackedFetch(
        withApiBase(`/api/project/${projectId}`),
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt_label: normalizedLabel }),
        },
        { source: "api" },
      );
      const payload = await response.json();
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error ?? "Failed to update project category label");
      }
      const updatedProject = payload?.data ?? {};
      dispatch({
        type: "PATCH_CURRENT_PROJECT",
        payload: {
          prompt_label: normalizedLabel,
          prompt_label_info: updatedProject?.prompt_label_info ?? null,
        },
      });
      await fetchProjects(projectId, false);
      addSystemLog(`Project category label updated: ${projectId} -> ${normalizedLabel}`);
    } catch (error) {
      addSystemLog(`Failed to save project category label: ${String(error)}`);
    }
  };

  const updateProjectOntologyTypes = async (
    projectId,
    { entityTypeNames, edgeTypeNames, entityTypes, edgeTypes, preserveGraphStatus = true },
  ) => {
    const normalizedProjectId = normalizeProjectId(projectId);
    if (!normalizedProjectId) {
      throw new Error("project_id is required");
    }

    const hasDefinitionPayload = Array.isArray(entityTypes) || Array.isArray(edgeTypes);
    const nextOntology = hasDefinitionPayload
      ? buildUpdatedOntologyFromDefinitions(state.currentProject?.ontology, entityTypes, edgeTypes)
      : buildUpdatedOntologyFromTypeNames(
          state.currentProject?.ontology,
          entityTypeNames,
          edgeTypeNames,
        );

    addSystemLog(`Saving ontology edits for ${normalizedProjectId}...`);
    const response = await trackedFetch(
      withApiBase(`/api/project/${normalizedProjectId}`),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ontology: nextOntology,
          preserve_graph_status: Boolean(preserveGraphStatus),
        }),
      },
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to update ontology");
    }

    const updatedProject = payload?.data ?? {};
    const updatedOntology = updatedProject?.ontology ?? nextOntology;
    const entityTypeCount = updatedOntology?.entity_types?.length ?? 0;
    const edgeTypeCount = updatedOntology?.edge_types?.length ?? 0;
    dispatch({
      type: "PATCH_CURRENT_PROJECT",
      payload: {
        ...updatedProject,
        project_id: updatedProject?.project_id ?? normalizedProjectId,
        status: updatedProject?.status ?? "ontology_generated",
        ontology: updatedOntology,
        zep_graph_id: updatedProject?.zep_graph_id ?? "",
        graph_id: updatedProject?.zep_graph_id ?? "",
        project_workspace_id: updatedProject?.project_workspace_id ?? "",
        zep_graph_address: updatedProject?.zep_graph_address ?? "",
        graph_build_task_id: "",
        error: null,
      },
    });
    dispatch({
      type: "PATCH_ONTOLOGY_TASK",
      payload: {
        status: "success",
        message: "Ontology updated. Step B will use the latest types.",
        progress: 100,
        taskId: "",
        entityTypes: entityTypeCount,
        edgeTypes: edgeTypeCount,
      },
    });
    dispatch({
      type: "PATCH_GRAPH_TASK",
      payload: {
        status: "idle",
        message: "Ready to build graph",
        progress: 0,
        taskId: "",
        nodeCount: 0,
        edgeCount: 0,
        chunkCount: 0,
      },
    });
    await fetchProjects(normalizedProjectId, false);
    addSystemLog(
      `Ontology updated for ${normalizedProjectId} (${entityTypeCount} entity type${entityTypeCount === 1 ? "" : "s"}, ${edgeTypeCount} relationship type${edgeTypeCount === 1 ? "" : "s"}).`,
    );
    return updatedProject;
  };

  const fetchProjectOntologyVersions = async (projectId, limit = 30) => {
    const normalizedProjectId = normalizeProjectId(projectId);
    if (!normalizedProjectId) {
      throw new Error("project_id is required");
    }
    const response = await trackedFetch(
      withApiBase(`/api/project/${normalizedProjectId}/ontology-versions?limit=${Number(limit) || 30}`),
      undefined,
      { source: "api" },
    );
    const payload = await parseJsonResponse(response);
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to load ontology versions");
    }
    return Array.isArray(payload?.data) ? payload.data : [];
  };

  const mergeProjectOntology = async (
    projectId,
    { incomingOntology, baseOntology, preserveGraphStatus = true } = {},
  ) => {
    const normalizedProjectId = normalizeProjectId(projectId);
    if (!normalizedProjectId) {
      throw new Error("project_id is required");
    }
    const response = await trackedFetch(
      withApiBase(`/api/project/${normalizedProjectId}/ontology/merge`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          incoming_ontology: incomingOntology,
          base_ontology: baseOntology,
          preserve_graph_status: Boolean(preserveGraphStatus),
        }),
      },
      { source: "api" },
    );
    const payload = await parseJsonResponse(response);
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to merge ontology");
    }
    const updatedOntology = payload?.data?.ontology ?? {};
    dispatch({
      type: "PATCH_CURRENT_PROJECT",
      payload: {
        ontology: updatedOntology,
      },
    });
    return payload?.data;
  };

  return {
    switchProject,
    fetchProjects,
    refreshProjects,
    updateProjectName,
    updateProjectRefreshDataWhileBuild,
    deleteProject,
    setProjectPromptLabel,
    updateProjectOntologyTypes,
    fetchProjectOntologyVersions,
    mergeProjectOntology,
  };
}

export { createProjectActions };
