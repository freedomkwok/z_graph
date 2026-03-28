import { readLastProjectId, rememberLastProjectId } from "../storage";
import {
  buildGraphDataApiPath,
  buildUpdatedOntologyFromDefinitions,
  buildUpdatedOntologyFromTypeNames,
  getPreferredPromptLabel,
  normalizeNonNegativeInteger,
  normalizePositiveInteger,
  normalizeProjectId,
  parseJsonResponse,
} from "../utils";
import { getGraphTaskFromProject, getOntologyTaskFromProject, initialGraphTask, initialOntologyTask } from "../state";

function createProjectActions({
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
}) {
  async function switchProject(projectId, preferredWorkspaceId = "") {
    const selectedProjectId = (projectId ?? "").trim();
    setFormField("projectId", selectedProjectId);
    rememberLastProjectId(selectedProjectId);

    if (!selectedProjectId) {
      dispatch({ type: "SET_ONTOLOGY_TASK", payload: initialOntologyTask });
      dispatch({ type: "SET_GRAPH_TASK", payload: initialGraphTask });
      dispatch({ type: "SET_CURRENT_PROJECT", payload: null });
      setFormFields({
        promptLabel: getPreferredPromptLabel(state.promptLabelCatalog.items, "Production"),
        graphName: "",
        chunkSize: 500,
        chunkOverlap: 50,
      });
      lastOntologyTaskMessageRef.current = "";
      lastGraphTaskMessageRef.current = "";
      seenOntologyLatencyEventIdsRef.current = new Set();
      seenGraphLatencyEventIdsRef.current = new Set();
      addSystemLog("No project selected.");
      return;
    }

    addSystemLog(`Loading project ${selectedProjectId}...`);
    try {
      const response = await fetch(withApiBase(`/api/project/${selectedProjectId}`));
      const payload = await response.json();
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
      setFormFields({
        projectId: hydratedProject.project_id ?? selectedProjectId,
        projectName: hydratedProject.name ?? "IMP Graph Project",
        simulationRequirement: hydratedProject.context_requirement ?? "",
        graphName: "",
        chunkSize: normalizePositiveInteger(hydratedProject.chunk_size, 500),
        chunkOverlap: normalizeNonNegativeInteger(hydratedProject.chunk_overlap, 50),
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
      const projectGraphId = hydratedProject?.zep_graph_id ?? hydratedProject?.graph_id ?? "";
      const projectWorkspaceId = hydratedProject?.project_workspace_id ?? hydratedProject?.workspace_id;
      if (hydratedProject?.status === "graph_completed" && projectGraphId) {
        try {
          const graphResponse = await fetch(
            withApiBase(buildGraphDataApiPath(projectGraphId, projectWorkspaceId)),
          );
          const graphPayload = await graphResponse.json();
          if (graphResponse.ok && graphPayload?.success && graphPayload?.data) {
            const graphData = graphPayload.data;
            nextGraphTask = {
              ...nextGraphTask,
              nodeCount: graphData.node_count ?? graphData.nodes?.length ?? 0,
              edgeCount: graphData.edge_count ?? graphData.edges?.length ?? 0,
            };
          }
        } catch {
          // Ignore graph stat retrieval errors here.
        }
      }

      dispatch({
        type: "SET_GRAPH_TASK",
        payload: nextGraphTask,
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
      const response = await fetch(withApiBase("/api/project/list?limit=200"));
      const payload = await response.json();
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
    const response = await fetch(withApiBase(`/api/project/${normalizedProjectId}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: normalizedName }),
    });
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
    const response = await fetch(withApiBase(`/api/project/${normalizedProjectId}`), {
      method: "DELETE",
    });
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
      const response = await fetch(withApiBase(`/api/project/${projectId}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_label: normalizedLabel }),
      });
      const payload = await response.json();
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error ?? "Failed to update project category label");
      }
      dispatch({
        type: "PATCH_CURRENT_PROJECT",
        payload: { prompt_label: normalizedLabel },
      });
      await fetchProjects(projectId, false);
      addSystemLog(`Project category label updated: ${projectId} -> ${normalizedLabel}`);
    } catch (error) {
      addSystemLog(`Failed to save project category label: ${String(error)}`);
    }
  };

  const updateProjectOntologyTypes = async (
    projectId,
    { entityTypeNames, edgeTypeNames, entityTypes, edgeTypes },
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
    const response = await fetch(withApiBase(`/api/project/${normalizedProjectId}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ontology: nextOntology }),
    });
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

  return {
    switchProject,
    fetchProjects,
    refreshProjects,
    updateProjectName,
    deleteProject,
    setProjectPromptLabel,
    updateProjectOntologyTypes,
  };
}

export { createProjectActions };
