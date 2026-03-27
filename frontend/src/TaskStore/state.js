import { BACKEND_DISPLAY_URL, MAX_SYSTEM_LOGS } from "./constants";

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

export {
  initialOntologyTask,
  initialGraphTask,
  initialState,
  getOntologyTaskFromProject,
  getGraphTaskFromProject,
  taskReducer,
};
