import { useMemo } from "react";

import { useTaskStore } from "./taskStore";

export default function TopBar() {
  const { state, setViewMode, switchProject, checkBackendHealth, refreshProjects } =
    useTaskStore();
  const { viewMode, backendHealth, projectCatalog, form } = state;

  const healthText = useMemo(() => {
    if (backendHealth.loading) return "Checking";
    return backendHealth.online ? "Online" : "Offline";
  }, [backendHealth.loading, backendHealth.online]);

  const hasSelectedProject = useMemo(
    () => projectCatalog.items.some((project) => project.project_id === form.projectId),
    [projectCatalog.items, form.projectId],
  );

  return (
    <header className="topbar">
      <div className="brand">zep_graph</div>

      <div className="topbar-controls">
        <div className="project-picker">
          <span className="project-label">Project</span>
          <select
            className="project-select"
            value={form.projectId}
            onChange={(event) => switchProject(event.target.value)}
            disabled={projectCatalog.loading || !projectCatalog.items.length}
            title="Switch project"
          >
            <option value="">
              {projectCatalog.loading ? "Loading projects..." : "Select project"}
            </option>
            {form.projectId && !hasSelectedProject && (
              <option value={form.projectId}>{form.projectId} (manual)</option>
            )}
            {projectCatalog.items.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.project_id} | {project.name}
              </option>
            ))}
          </select>
          <button
            className="icon-btn"
            type="button"
            onClick={refreshProjects}
            disabled={projectCatalog.loading}
            title="Refresh project list"
          >
            ↻
          </button>
        </div>

        <div className="view-switcher">
          <button
            className={`switch-btn ${viewMode === "both" ? "active" : ""}`}
            type="button"
            onClick={() => setViewMode("both")}
          >
            Both
          </button>
          <button
            className={`switch-btn ${viewMode === "backend" ? "active" : ""}`}
            type="button"
            onClick={() => setViewMode("backend")}
          >
            Backend
          </button>
        </div>
      </div>

      <div className="backend-status-wrap">
        <span className={`status-dot ${backendHealth.online ? "online" : "offline"}`} />
        <span className="status-text">Backend {healthText}</span>
        <button
          className="icon-btn"
          type="button"
          onClick={checkBackendHealth}
          disabled={backendHealth.loading}
          title="Refresh backend status"
        >
          ↻
        </button>
      </div>
    </header>
  );
}
