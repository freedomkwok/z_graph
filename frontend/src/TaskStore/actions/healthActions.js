import { BACKEND_DISPLAY_URL } from "../constants";

function createHealthActions({ dispatch, addSystemLog, withApiBase, trackedFetch }) {
  const normalizeTaskPollIntervalMs = (value, fallback = 2000) => {
    const parsed = Number.parseInt(String(value ?? ""), 10);
    if (!Number.isFinite(parsed) || parsed < 500) return fallback;
    return parsed;
  };

  const normalizeGraphDataPollIntervalMs = (value, fallback = 10000) => {
    const parsed = Number.parseInt(String(value ?? ""), 10);
    if (!Number.isFinite(parsed) || parsed < 2000) return fallback;
    return parsed;
  };

  const normalizeGraphitiEmbeddingModelOptions = (value) => {
    const options = Array.isArray(value)
      ? value.map((item) => String(item ?? "").trim()).filter(Boolean)
      : String(value ?? "")
          .split(",")
          .map((item) => String(item ?? "").trim())
          .filter(Boolean);
    return options.length ? options : ["text-embedding-3-large"];
  };

  const checkBackendHealth = async () => {
    dispatch({ type: "PATCH_BACKEND_HEALTH", payload: { loading: true } });
    let latencyMs = null;
    try {
      const startedAt =
        typeof performance !== "undefined" && typeof performance.now === "function"
          ? performance.now()
          : Date.now();
      const healthResponse = await (trackedFetch || fetch)(
        withApiBase("/api/health"),
        {
          cache: "no-store",
          headers: { Accept: "application/json" },
        },
        { source: "health" },
      );
      const endedAt =
        typeof performance !== "undefined" && typeof performance.now === "function"
          ? performance.now()
          : Date.now();
      latencyMs = Math.max(0, Math.round(endedAt - startedAt));
      const healthData = await healthResponse.json();

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

      dispatch({
        type: "SET_BACKEND_HEALTH",
        payload: {
          loading: false,
          online: true,
          url: BACKEND_DISPLAY_URL,
          environment: healthData.environment ?? "-",
          zepBackend: String(healthData.zep_backend ?? healthData.zepBackend ?? "").trim(),
          zepConfigured: Boolean(healthData.zep_configured ?? healthData.zepConfigured),
          graphBackendOptions: {
            zep_cloud: Boolean(healthData?.graph_backend_options?.zep_cloud),
            neo4j: Boolean(healthData?.graph_backend_options?.neo4j),
            oracle: Boolean(healthData?.graph_backend_options?.oracle),
          },
          taskPollIntervalMs: normalizeTaskPollIntervalMs(healthData?.task_poll_interval_ms),
          graphDataPollIntervalMs: normalizeGraphDataPollIntervalMs(
            healthData?.graph_data_poll_interval_ms,
          ),
          graphitiEmbeddingModelOptions: normalizeGraphitiEmbeddingModelOptions(
            healthData?.graphiti_embedding_model_options,
          ),
          graphitiDefaultEmbeddingModel:
            String(healthData?.graphiti_default_embedding_model ?? "").trim() ||
            "text-embedding-3-large",
          graphitiTracingDefaultEnabled: Boolean(healthData?.graphiti_tracing_default_enabled),
          latencyMs,
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
          url: BACKEND_DISPLAY_URL,
          environment: "-",
          zepBackend: "",
          zepConfigured: false,
          graphBackendOptions: {
            zep_cloud: false,
            neo4j: false,
            oracle: false,
          },
          taskPollIntervalMs: 2000,
          graphDataPollIntervalMs: 10000,
          graphitiEmbeddingModelOptions: ["text-embedding-3-large"],
          graphitiDefaultEmbeddingModel: "text-embedding-3-large",
          graphitiTracingDefaultEnabled: true,
          latencyMs,
          message: String(error),
        },
      });
    }
  };

  return { checkBackendHealth };
}

export { createHealthActions };
