import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function resolveProjectDetailRequestTimeoutMs(mode) {
  const fileEnv = loadEnv(mode, process.cwd(), "");
  const raw = String(
    process.env.PROJECT_DETAIL_REQUEST_TIMEOUT_MS ??
      fileEnv.PROJECT_DETAIL_REQUEST_TIMEOUT_MS ??
      "30000",
  ).trim();
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 30000;
}

export default defineConfig(({ mode }) => {
  const projectDetailRequestTimeoutMs = resolveProjectDetailRequestTimeoutMs(mode);

  return {
    plugins: [react()],
    define: {
      __PROJECT_DETAIL_REQUEST_TIMEOUT_MS__: JSON.stringify(projectDetailRequestTimeoutMs),
    },
    server: {
      proxy: {
        "/api": {
          target: "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
