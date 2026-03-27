import { createContext, useContext, useEffect, useReducer, useRef } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";
const LAST_PROJECT_ID_KEY = "z_graph.last_project_id";
const resolveBackendUrl = () => {
  if (API_BASE_URL) return API_BASE_URL;
  if (typeof window !== "undefined") {
    const { protocol, hostname, port } = window.location;
    if (port === "5173" || port === "4173") {
      return `${protocol}//${hostname}:8000`;
    }
    return `${protocol}//${hostname}${port ? `:${port}` : ""}`;
  }
  return "http://localhost:8000";
};
const BACKEND_DISPLAY_URL = resolveBackendUrl();

const withApiBase = (path) => `${API_BASE_URL}${path}`;
const MAX_SYSTEM_LOGS = 200;

function normalizeProjectId(value) {
  return String(value ?? "").trim();
}

function normalizePositiveInteger(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function normalizeNonNegativeInteger(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function normalizePromptLabel(value) {
  const normalized = String(value ?? "").trim();
  return normalized || "Production";
}

function rememberLastProjectId(projectId) {
  if (typeof window === "undefined") return;
  const normalized = normalizeProjectId(projectId);
  if (normalized) {
    window.localStorage.setItem(LAST_PROJECT_ID_KEY, normalized);
  } else {
    window.localStorage.removeItem(LAST_PROJECT_ID_KEY);
  }
}

function readLastProjectId() {
  if (typeof window === "undefined") return "";
  return normalizeProjectId(window.localStorage.getItem(LAST_PROJECT_ID_KEY));
}

function getPreferredPromptLabel(catalogItems, desiredLabel) {
  const normalizedDesired = normalizePromptLabel(desiredLabel);
  const labels = Array.isArray(catalogItems) ? catalogItems : [];
  if (!labels.length) return normalizedDesired || "Production";
  const hasDesired = labels.some(
    (item) => String(item?.name ?? "").toLowerCase() === normalizedDesired.toLowerCase(),
  );
  if (hasDesired) return normalizedDesired;
  const production = labels.find(
    (item) => String(item?.name ?? "").toLowerCase() === "production",
  );
  if (production?.name) return String(production.name);
  return String(labels[0]?.name ?? "Production");
}

const initialOntologyTask = {
  status: "idle",
  message: "Waiting",
  progress: 0,
  taskId: "",
  entityTypes: 0,
  edgeTypes: 0,
};

const initialGraphTask = {
  status: "idle",
  message: "Waiting",
  progress: 0,
  taskId: "",
  nodeCount: 0,
  edgeCount: 0,
  chunkCount: 0,
};

const initialState = {
  viewMode: "both",
  backendHealth: {
    loading: false,
    online: false,
    url: BACKEND_DISPLAY_URL,
    environment: "-",
    zepConfigured: false,
    latencyMs: null,
    message: "Not checked",
  },
  iframeVersion: 0,
  form: {
    files: [],
    simulationRequirement: "",
    projectName: "IMP Graph Project",
    additionalContext: "",
    promptLabel: "Production",
    graphName: "",
    chunkSize: 500,
    chunkOverlap: 50,
    projectId: "",
  },
  promptLabelCatalog: {
    loading: false,
    error: "",
    items: [],
    totalLabels: 0,
  },
  projectCatalog: {
    loading: false,
    error: "",
    items: [],
  },
  currentProject: null,
  ontologyTask: initialOntologyTask,
  graphTask: initialGraphTask,
  systemLogs: [],
};

function formatLogTime(date = new Date()) {
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const seconds = String(date.getSeconds()).padStart(2, "0");
  const millis = String(date.getMilliseconds()).padStart(3, "0");
  return `${hours}:${minutes}:${seconds}.${millis}`;
}

function appendSystemLog(existingLogs, message) {
  const log = { time: formatLogTime(), msg: String(message) };
  const next = [...existingLogs, log];
  if (next.length <= MAX_SYSTEM_LOGS) return next;
  return next.slice(next.length - MAX_SYSTEM_LOGS);
}

async function parseJsonResponse(response, endpointLabel) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${endpointLabel} returned non-JSON response`);
  }
}

function buildGraphDataApiPath(graphId, projectWorkspaceId) {
  const params = new URLSearchParams({ include_episode_data: "false" });
  const normalizedWorkspaceId = String(projectWorkspaceId ?? "").trim();
  if (normalizedWorkspaceId) {
    params.set("project_workspace_id", normalizedWorkspaceId);
  }
  return `/api/data/${encodeURIComponent(String(graphId ?? "").trim())}?${params.toString()}`;
}

function getOntologyTaskFromProject(project) {
  const entityTypes = project?.ontology?.entity_types?.length ?? 0;
  const edgeTypes = project?.ontology?.edge_types?.length ?? 0;
  const hasOntology = entityTypes > 0 || edgeTypes > 0;

  if (project?.status === "failed" && !hasOntology) {
    return {
      ...initialOntologyTask,
      status: "error",
      message: project?.error ?? "Ontology generation failed",
      entityTypes,
      edgeTypes,
    };
  }

  if (hasOntology || project?.status !== "created") {
    return {
      ...initialOntologyTask,
      status: "success",
      message: "Ontology ready",
      progress: 100,
      entityTypes,
      edgeTypes,
    };
  }

  return initialOntologyTask;
}

function getGraphTaskFromProject(project) {
  switch (project?.status) {
    case "graph_building":
      return {
        ...initialGraphTask,
        status: "running",
        message: "Graph build in progress",
        taskId: project?.graph_build_task_id ?? "",
      };
    case "graph_completed":
      return {
        ...initialGraphTask,
        status: "success",
        message: "Graph build completed",
        progress: 100,
      };
    case "failed":
      return {
        ...initialGraphTask,
        status: "error",
        message: project?.error ?? "Graph build failed",
      };
    case "ontology_generated":
      return {
        ...initialGraphTask,
        status: "idle",
        message: "Ready to build graph",
      };
    default:
      return initialGraphTask;
  }
}

function taskReducer(state, action) {
  switch (action.type) {
    case "SET_VIEW_MODE":
      return { ...state, viewMode: action.payload };
    case "INCREMENT_IFRAME_VERSION":
      return { ...state, iframeVersion: state.iframeVersion + 1 };
    case "SET_BACKEND_HEALTH":
      return { ...state, backendHealth: action.payload };
    case "PATCH_BACKEND_HEALTH":
      return {
        ...state,
        backendHealth: { ...state.backendHealth, ...action.payload },
      };
    case "SET_FORM_FIELD":
      return {
        ...state,
        form: { ...state.form, [action.field]: action.value },
      };
    case "SET_FILES":
      return {
        ...state,
        form: { ...state.form, files: action.payload },
      };
    case "SET_FORM_FIELDS":
      return {
        ...state,
        form: { ...state.form, ...action.payload },
      };
    case "SET_PROMPT_LABEL_CATALOG":
      return {
        ...state,
        promptLabelCatalog: action.payload,
      };
    case "PATCH_PROMPT_LABEL_CATALOG":
      return {
        ...state,
        promptLabelCatalog: { ...state.promptLabelCatalog, ...action.payload },
      };
    case "SET_PROJECT_CATALOG":
      return {
        ...state,
        projectCatalog: action.payload,
      };
    case "SET_CURRENT_PROJECT":
      return {
        ...state,
        currentProject: action.payload,
      };
    case "PATCH_CURRENT_PROJECT":
      return {
        ...state,
        currentProject: state.currentProject
          ? { ...state.currentProject, ...action.payload }
          : action.payload,
      };
    case "PATCH_PROJECT_CATALOG":
      return {
        ...state,
        projectCatalog: { ...state.projectCatalog, ...action.payload },
      };
    case "SET_ONTOLOGY_TASK":
      return { ...state, ontologyTask: action.payload };
    case "PATCH_ONTOLOGY_TASK":
      return {
        ...state,
        ontologyTask: { ...state.ontologyTask, ...action.payload },
      };
    case "SET_GRAPH_TASK":
      return { ...state, graphTask: action.payload };
    case "PATCH_GRAPH_TASK":
      return {
        ...state,
        graphTask: { ...state.graphTask, ...action.payload },
      };
    case "ADD_SYSTEM_LOG":
      return {
        ...state,
        systemLogs: appendSystemLog(state.systemLogs, action.payload),
      };
    case "CLEAR_SYSTEM_LOGS":
      return {
        ...state,
        systemLogs: [],
      };
    default:
      return state;
  }
}

const TaskStoreContext = createContext(null);

export function TaskStoreProvider({ children }) {
  const [state, dispatch] = useReducer(taskReducer, initialState);
  const lastOntologyTaskMessageRef = useRef("");
  const lastGraphTaskMessageRef = useRef("");

  const addSystemLog = (message) => {
    if (!message) return;
    dispatch({ type: "ADD_SYSTEM_LOG", payload: message });
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

  const fetchPromptLabels = async ({ syncFormLabel = true } = {}) => {
    dispatch({
      type: "PATCH_PROMPT_LABEL_CATALOG",
      payload: { loading: true, error: "" },
    });
    try {
      const response = await fetch(withApiBase("/api/prompt-label/list"));
      const payload = await response.json();
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error ?? "Failed to list prompt labels");
      }
      const labels = Array.isArray(payload?.data) ? payload.data : [];
      const parsedTotalLabels = Number(payload?.total_labels);
      const totalLabels = Number.isFinite(parsedTotalLabels) ? parsedTotalLabels : labels.length;
      dispatch({
        type: "SET_PROMPT_LABEL_CATALOG",
        payload: { loading: false, error: "", items: labels, totalLabels },
      });
      if (syncFormLabel) {
        const nextPromptLabel = getPreferredPromptLabel(labels, state.form.promptLabel);
        setFormField("promptLabel", nextPromptLabel);
      }
      return labels;
    } catch (error) {
      dispatch({
        type: "PATCH_PROMPT_LABEL_CATALOG",
        payload: { loading: false, error: String(error), totalLabels: state.promptLabelCatalog.totalLabels },
      });
      addSystemLog(`Exception in listPromptLabels: ${String(error)}`);
      return [];
    }
  };

  const createPromptLabel = async (name) => {
    const normalizedName = String(name ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }
    const response = await fetch(withApiBase("/api/prompt-label"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: normalizedName }),
    });
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to create prompt label");
    }
    await fetchPromptLabels({ syncFormLabel: false });
    addSystemLog(`Prompt label saved: ${payload?.data?.name ?? normalizedName}`);
    return payload?.data;
  };

  const deletePromptLabel = async (name) => {
    const normalizedName = String(name ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }
    const response = await fetch(withApiBase(`/api/prompt-label/${encodeURIComponent(normalizedName)}`), {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to delete prompt label");
    }
    const labels = await fetchPromptLabels({ syncFormLabel: false });
    const nextPromptLabel = getPreferredPromptLabel(labels, state.form.promptLabel);
    if (nextPromptLabel !== state.form.promptLabel) {
      setFormField("promptLabel", nextPromptLabel);
    }
    addSystemLog(`Prompt label deleted: ${normalizedName}`);
    return true;
  };

  const syncPromptLabelFromLangfuse = async (name) => {
    const normalizedName = String(name ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }
    const response = await fetch(
      withApiBase(`/api/prompt-label/${encodeURIComponent(normalizedName)}/sync-from-langfuse`),
      {
        method: "POST",
      },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to sync prompts from Langfuse");
    }
    await fetchPromptLabels({ syncFormLabel: false });
    const downloadedFiles = Number(payload?.data?.downloaded_files ?? 0);
    addSystemLog(
      `Prompt label synced from Langfuse: ${normalizedName} (${downloadedFiles} file${downloadedFiles === 1 ? "" : "s"})`,
    );
    return payload?.data;
  };

  async function switchProject(projectId, preferredWorkspaceId = "") {
    const selectedProjectId = (projectId ?? "").trim();
    setFormField("projectId", selectedProjectId);
    rememberLastProjectId(selectedProjectId);

    if (!selectedProjectId) {
      dispatch({ type: "SET_ONTOLOGY_TASK", payload: initialOntologyTask });
      dispatch({ type: "SET_GRAPH_TASK", payload: initialGraphTask });
      dispatch({ type: "SET_CURRENT_PROJECT", payload: null });
      setFormFields({
        promptLabel: getPreferredPromptLabel(state.promptLabelCatalog.items, state.form.promptLabel),
        graphName: "",
        chunkSize: 500,
        chunkOverlap: 50,
      });
      lastOntologyTaskMessageRef.current = "";
      lastGraphTaskMessageRef.current = "";
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
          hydratedProject.prompt_label ?? state.form.promptLabel,
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

  const setProjectPromptLabel = async (label) => {
    const normalizedLabel = getPreferredPromptLabel(state.promptLabelCatalog.items, label);
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
        throw new Error(payload?.error ?? "Failed to update project prompt label");
      }
      dispatch({
        type: "PATCH_CURRENT_PROJECT",
        payload: { prompt_label: normalizedLabel },
      });
      await fetchProjects(projectId, false);
      addSystemLog(`Project prompt label updated: ${projectId} -> ${normalizedLabel}`);
    } catch (error) {
      addSystemLog(`Failed to save project prompt label: ${String(error)}`);
    }
  };

  const checkBackendHealth = async () => {
    dispatch({ type: "PATCH_BACKEND_HEALTH", payload: { loading: true } });
    let latencyMs = null;
    try {
      const startedAt =
        typeof performance !== "undefined" && typeof performance.now === "function"
          ? performance.now()
          : Date.now();
      const healthResponse = await fetch(withApiBase("/api/health"), {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      const endedAt =
        typeof performance !== "undefined" && typeof performance.now === "function"
          ? performance.now()
          : Date.now();
      latencyMs = Math.max(0, Math.round(endedAt - startedAt));
      const healthData = await parseJsonResponse(healthResponse, "/api/health");

      if (!healthResponse.ok) {
        throw new Error(healthData?.error ?? "Health check failed");
      }

      const hasExpectedHealthShape =
        healthData?.status === "ok" &&
        typeof healthData?.environment === "string" &&
        (Object.prototype.hasOwnProperty.call(healthData, "zep_configured") ||
          Object.prototype.hasOwnProperty.call(healthData, "zepConfigured"));

      if (!hasExpectedHealthShape) {
        throw new Error("Health endpoint reachable, but payload is not z_graph backend");
      }

      let message = "Healthy";
      try {
        const projectsResponse = await fetch(withApiBase("/api/project/list?limit=1"), {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        const projectsData = await parseJsonResponse(projectsResponse, "/api/project/list");
        const hasExpectedProjectsShape =
          projectsResponse.ok && projectsData?.success === true && Array.isArray(projectsData?.data);
        if (!hasExpectedProjectsShape) {
          message = "Healthy (project API check warning)";
        }
      } catch {
        message = "Healthy (project API check warning)";
      }

      dispatch({
        type: "SET_BACKEND_HEALTH",
        payload: {
          loading: false,
          online: true,
          url: BACKEND_DISPLAY_URL,
          environment: healthData.environment ?? "-",
          zepConfigured: Boolean(healthData.zep_configured ?? healthData.zepConfigured),
          latencyMs,
          message,
        },
      });
    } catch (error) {
      addSystemLog(`Health check failed: ${String(error)}`);
      dispatch({
        type: "SET_BACKEND_HEALTH",
        payload: {
          loading: false,
          online: false,
          url: BACKEND_DISPLAY_URL,
          environment: "-",
          zepConfigured: false,
          latencyMs,
          message: String(error),
        },
      });
    }
  };

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

  const runGraphBuild = async () => {
    const { projectId, graphName, chunkSize, chunkOverlap } = state.form;
    const existingGraphId = String(
      state.currentProject?.zep_graph_id ?? state.currentProject?.graph_id ?? "",
    ).trim();
    if (!projectId.trim()) {
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

  useEffect(() => {
    addSystemLog("Project view initialized.");
    checkBackendHealth();
    fetchPromptLabels({ syncFormLabel: true }).then(() => {
      fetchProjects(undefined, true);
    });
    const timer = setInterval(checkBackendHealth, 30000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!state.ontologyTask.taskId) return undefined;

    let cancelled = false;
    const { taskId } = state.ontologyTask;
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
            await switchProject(nextProjectId);
            await fetchProjects(nextProjectId, false);
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
          },
        });
      } catch (error) {
        if (cancelled) return;
        addSystemLog(`Exception in pollOntologyTaskStatus: ${String(error)}`);
        dispatch({
          type: "PATCH_ONTOLOGY_TASK",
          payload: {
            status: "error",
            message: String(error),
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
  }, [state.ontologyTask.taskId]);

  useEffect(() => {
    if (!state.graphTask.taskId) return undefined;

    let cancelled = false;
    const { taskId } = state.graphTask;
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
                project_workspace_id: task.result?.project_workspace_id ?? "",
                zep_graph_address: task.result?.zep_graph_address ?? "",
                status: "graph_completed",
              },
            });
          }
          addSystemLog("Graph build completed.");
          fetchProjects(state.form.projectId, false);
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
          fetchProjects(state.form.projectId, false);
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
        addSystemLog(`Exception in pollTaskStatus: ${String(error)}`);
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
    fetchPromptLabels,
    createPromptLabel,
    deletePromptLabel,
    syncPromptLabelFromLangfuse,
    setProjectPromptLabel,
    setFiles,
    switchProject,
    fetchProjects,
    refreshProjects,
    updateProjectName,
    deleteProject,
    checkBackendHealth,
    runOntologyGenerate,
    runGraphBuild,
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
