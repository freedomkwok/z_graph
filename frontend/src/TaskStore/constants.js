const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";
const LAST_PROJECT_ID_KEY = "z_graph.last_project_id";
const MAX_SYSTEM_LOGS = 200;

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

export { API_BASE_URL, LAST_PROJECT_ID_KEY, MAX_SYSTEM_LOGS, BACKEND_DISPLAY_URL, withApiBase };
