import { createContext, useContext, useEffect, useReducer, useRef } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

const withApiBase = (path) => `${API_BASE_URL}${path}`;
const MAX_SYSTEM_LOGS = 200;

const initialOntologyTask = {
  status: "idle",
  message: "Waiting",
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
    environment: "-",
    zepConfigured: false,
    message: "Not checked",
  },
  iframeVersion: 0,
  form: {
    files: [],
    simulationRequirement: "",
    projectName: "IMP Graph Project",
    additionalContext: "",
    projectId: "",
  },
  projectCatalog: {
    loading: false,
    error: "",
    items: [],
  },
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

function getOntologyTaskFromProject(project) {
  const entityTypes = project?.ontology?.entity_types?.length ?? 0;
  const edgeTypes = project?.ontology?.edge_types?.length ?? 0;
  const hasOntology = entityTypes > 0 || edgeTypes > 0;

  if (project?.status === "failed" && !hasOntology) {
    return {
      status: "error",
      message: project?.error ?? "Ontology generation failed",
      entityTypes,
      edgeTypes,
    };
  }

  if (hasOntology || project?.status !== "created") {
    return {
      status: "success",
      message: "Ontology ready",
      entityTypes,
      edgeTypes,
    };
  }

  return {
    status: "idle",
    message: "Waiting",
    entityTypes: 0,
    edgeTypes: 0,
  };
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
    case "SET_PROJECT_CATALOG":
      return {
        ...state,
        projectCatalog: action.payload,
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
  const lastPolledTaskMessageRef = useRef("");

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

  async function switchProject(projectId) {
    const selectedProjectId = (projectId ?? "").trim();
    setFormField("projectId", selectedProjectId);

    if (!selectedProjectId) {
      dispatch({ type: "SET_ONTOLOGY_TASK", payload: initialOntologyTask });
      dispatch({ type: "SET_GRAPH_TASK", payload: initialGraphTask });
      lastPolledTaskMessageRef.current = "";
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
      setFormFields({
        projectId: project.project_id ?? selectedProjectId,
        projectName: project.name ?? "IMP Graph Project",
        simulationRequirement: project.context_requirement ?? "",
      });

      dispatch({
        type: "SET_ONTOLOGY_TASK",
        payload: getOntologyTaskFromProject(project),
      });

      let nextGraphTask = getGraphTaskFromProject(project);
      if (project?.status === "graph_completed" && project?.graph_id) {
        try {
          const graphResponse = await fetch(withApiBase(`/api/data/${project.graph_id}`));
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
      lastPolledTaskMessageRef.current = "";
      addSystemLog(
        `Project loaded: ${project.project_id} (${project.status ?? "unknown status"})`,
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
      const hasRequested = requested && projects.some((p) => p.project_id === requested);
      const hasSelected = selectedFromState && projects.some((p) => p.project_id === selectedFromState);

      let nextProjectId = "";
      if (hasRequested) {
        nextProjectId = requested;
      } else if (hasSelected) {
        nextProjectId = selectedFromState;
      } else if (projects.length > 0) {
        nextProjectId = projects[0].project_id;
      }

      if (nextProjectId) {
        await switchProject(nextProjectId);
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

  const checkBackendHealth = async () => {
    dispatch({ type: "PATCH_BACKEND_HEALTH", payload: { loading: true } });
    try {
      const [healthResponse, projectsResponse] = await Promise.all([
        fetch(withApiBase("/api/health"), {
          cache: "no-store",
          headers: { Accept: "application/json" },
        }),
        fetch(withApiBase("/api/project/list?limit=1"), {
          cache: "no-store",
          headers: { Accept: "application/json" },
        }),
      ]);

      const [healthData, projectsData] = await Promise.all([
        parseJsonResponse(healthResponse, "/api/health"),
        parseJsonResponse(projectsResponse, "/api/project/list"),
      ]);

      if (!healthResponse.ok) {
        throw new Error(healthData?.error ?? "Health check failed");
      }
      if (!projectsResponse.ok) {
        throw new Error(projectsData?.error ?? "Project list check failed");
      }

      const hasExpectedHealthShape =
        healthData?.status === "ok" &&
        typeof healthData?.environment === "string" &&
        (Object.prototype.hasOwnProperty.call(healthData, "zep_configured") ||
          Object.prototype.hasOwnProperty.call(healthData, "zepConfigured"));

      const hasExpectedProjectsShape =
        projectsData?.success === true && Array.isArray(projectsData?.data);

      if (!hasExpectedHealthShape || !hasExpectedProjectsShape) {
        throw new Error("Health endpoint reachable, but payload is not zep_graph backend");
      }

      dispatch({
        type: "SET_BACKEND_HEALTH",
        payload: {
          loading: false,
          online: true,
          environment: healthData.environment ?? "-",
          zepConfigured: Boolean(healthData.zep_configured ?? healthData.zepConfigured),
          message: "Healthy",
        },
      });
    } catch (error) {
      addSystemLog(`Health check failed: ${String(error)}`);
      dispatch({
        type: "SET_BACKEND_HEALTH",
        payload: {
          loading: false,
          online: false,
          environment: "-",
          zepConfigured: false,
          message: String(error),
        },
      });
    }
  };

  const runOntologyGenerate = async () => {
    const { simulationRequirement, files, projectName, additionalContext } = state.form;

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
      payload: { status: "running", message: "Generating ontology..." },
    });
    addSystemLog("Starting ontology generation...");

    try {
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file));
      formData.append("simulation_requirement", simulationRequirement);
      formData.append("project_name", projectName);
      formData.append("additional_context", additionalContext);

      const response = await fetch(withApiBase("/api/ontology/generate"), {
        method: "POST",
        body: formData,
      });
      const payload = await response.json();

      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error ?? "Ontology generation failed");
      }

      const nextProjectId = payload?.data?.project_id ?? "";
      const entityTypes = payload?.data?.ontology?.entity_types?.length ?? 0;
      const edgeTypes = payload?.data?.ontology?.edge_types?.length ?? 0;

      dispatch({ type: "SET_FORM_FIELD", field: "projectId", value: nextProjectId });
      dispatch({
        type: "SET_ONTOLOGY_TASK",
        payload: {
          status: "success",
          message: `Ontology generated for ${nextProjectId}`,
          entityTypes,
          edgeTypes,
        },
      });
      addSystemLog(`Ontology generated for ${nextProjectId}.`);
      dispatch({
        type: "PATCH_GRAPH_TASK",
        payload: {
          status: "idle",
          message: "Ready to build graph",
          progress: 0,
          taskId: "",
        },
      });
      await fetchProjects(nextProjectId, false);
    } catch (error) {
      addSystemLog(`Exception in generateOntology: ${String(error)}`);
      dispatch({
        type: "PATCH_ONTOLOGY_TASK",
        payload: { status: "error", message: String(error) },
      });
    }
  };

  const runGraphBuild = async () => {
    const { projectId } = state.form;
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
    addSystemLog(`Starting graph build for ${projectId}...`);

    try {
      const response = await fetch(withApiBase("/api/build"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId }),
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
      lastPolledTaskMessageRef.current = submittedMessage;
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
    fetchProjects(undefined, true);
    const timer = setInterval(checkBackendHealth, 30000);
    return () => clearInterval(timer);
  }, []);

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
        if (task.message && task.message !== lastPolledTaskMessageRef.current) {
          lastPolledTaskMessageRef.current = task.message;
          addSystemLog(task.message);
        }

        if (task.status === "completed") {
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
    setFiles,
    switchProject,
    fetchProjects,
    refreshProjects,
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
