import { LAST_PROJECT_ID_KEY } from "./constants";
import { normalizeProjectId } from "./utils";

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

export { rememberLastProjectId, readLastProjectId };
