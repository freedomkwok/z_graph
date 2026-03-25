import { useEffect, useMemo, useRef, useState } from "react";

import { useTaskStore } from "./taskStore";

function formatProjectLabel(project) {
  const name = String(project?.name ?? "").trim() || "Unnamed Project";
  const projectId = String(project?.project_id ?? "").trim();
  const suffix = projectId ? projectId.slice(-8) : "--------";
  return `${name} (${suffix})`;
}

export default function TopBar({ currentPage = "workspace", onNavigate }) {
  const { state, setViewMode, switchProject, checkBackendHealth, refreshProjects } =
    useTaskStore();
  const { viewMode, backendHealth, projectCatalog, form } = state;
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsPinned, setSettingsPinned] = useState(false);
  const settingsMenuRef = useRef(null);
  const closeTimerRef = useRef(null);
  const backendStatusTitle = useMemo(() => {
    if (backendHealth.loading) return `Checking ${backendHealth.url}`;
    return backendHealth.online ? `Online: ${backendHealth.url}` : `Offline: ${backendHealth.url}`;
  }, [backendHealth.loading, backendHealth.online, backendHealth.url]);

  const hasSelectedProject = useMemo(
    () => projectCatalog.items.some((project) => project.project_id === form.projectId),
    [projectCatalog.items, form.projectId],
  );

  const clearCloseTimer = () => {
    if (!closeTimerRef.current) return;
    window.clearTimeout(closeTimerRef.current);
    closeTimerRef.current = null;
  };

  const closeSettingsMenu = () => {
    clearCloseTimer();
    setSettingsPinned(false);
    setSettingsOpen(false);
  };

  const scheduleSettingsClose = () => {
    clearCloseTimer();
    if (settingsPinned) return;
    closeTimerRef.current = window.setTimeout(() => {
      setSettingsOpen(false);
    }, 180);
  };

  const openSettingsPreview = () => {
    clearCloseTimer();
    setSettingsOpen(true);
  };

  const togglePinnedSettings = () => {
    clearCloseTimer();
    if (settingsPinned) {
      setSettingsPinned(false);
      setSettingsOpen(false);
      return;
    }
    setSettingsPinned(true);
    setSettingsOpen(true);
  };

  useEffect(() => {
    const onPointerDown = (event) => {
      if (!settingsMenuRef.current?.contains(event.target)) {
        closeSettingsMenu();
      }
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        closeSettingsMenu();
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
      clearCloseTimer();
    };
  }, []);

  return (
    <header className="topbar">
      <div className="brand">zep_graph</div>

      <div className="topbar-controls">
        <div className="project-picker">
          <div
            className="settings-menu"
            ref={settingsMenuRef}
            onMouseEnter={openSettingsPreview}
            onMouseLeave={scheduleSettingsClose}
          >
            <button
              className="icon-btn settings-trigger-btn"
              type="button"
              title="Settings"
              onClick={togglePinnedSettings}
            >
              ⚙
            </button>
            {settingsOpen && (
              <div className="settings-dropdown" role="menu">
                <button
                  className="settings-dropdown-item"
                  type="button"
                  onClick={() => {
                    closeSettingsMenu();
                    onNavigate?.("/settings/prompt-labels");
                  }}
                >
                  Prompt Label
                </button>
              </div>
            )}
          </div>
          <button
            className="project-label project-link-btn"
            type="button"
            onClick={() => onNavigate?.("/projects")}
            title="Open project management"
          >
            Project
          </button>
          <select
            className="project-select"
            value={form.projectId}
            onChange={(event) => {
              const selectedProjectId = event.target.value;
              const selectedProject = projectCatalog.items.find(
                (project) => project.project_id === selectedProjectId,
              );
              switchProject(selectedProjectId, selectedProject?.project_workspace_id ?? "");
            }}
            disabled={projectCatalog.loading || !projectCatalog.items.length}
            title="Switch project"
          >
            <option value="">
              {projectCatalog.loading ? "Loading projects..." : "Select project"}
            </option>
            {form.projectId && !hasSelectedProject && (
              <option value={form.projectId}>{`Manual (${form.projectId.slice(-8)})`}</option>
            )}
            {projectCatalog.items.map((project) => (
              <option key={project.project_id} value={project.project_id} title={project.project_id}>
                {formatProjectLabel(project)}
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

        {currentPage === "workspace" ? (
          <div className="view-switcher">
            <button
              className={`switch-btn ${viewMode === "both" ? "active" : ""}`}
              type="button"
              onClick={() => setViewMode("both")}
            >
              Backend + Graph
            </button>
            <button
              className={`switch-btn ${viewMode === "backend" ? "active" : ""}`}
              type="button"
              onClick={() => setViewMode("backend")}
            >
              Backend
            </button>
            <button
              className={`switch-btn ${viewMode === "graph" ? "active" : ""}`}
              type="button"
              onClick={() => setViewMode("graph")}
            >
              Graph
            </button>
          </div>
        ) : (
          <button className="switch-btn topbar-nav-btn" type="button" onClick={() => onNavigate?.("/")}>
            Back to Workspace
          </button>
        )}
      </div>

      <div className="backend-status-wrap">
        <span className={`status-dot ${backendHealth.online ? "online" : "offline"}`} />
        <span className="status-text" title={backendStatusTitle}>
          {backendHealth.url}
        </span>
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
