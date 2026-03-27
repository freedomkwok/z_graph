import { BACKEND_DISPLAY_URL } from "../constants";
import { parseJsonResponse } from "../utils";

function createHealthActions({ dispatch, addSystemLog, withApiBase }) {
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

  return { checkBackendHealth };
}

export { createHealthActions };
