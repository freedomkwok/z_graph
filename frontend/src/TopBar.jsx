import { useEffect, useMemo, useRef, useState } from "react";

import { useTaskStore } from "./TaskStore/index";
const NEW_PROJECT_OPTION_VALUE = "__new_project__";

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
  const [newProjectModalOpen, setNewProjectModalOpen] = useState(false);
  const [newProjectGraphBackend, setNewProjectGraphBackend] = useState("zep_cloud");
  const settingsMenuRef = useRef(null);
  const closeTimerRef = useRef(null);
  const graphBackendOptions = backendHealth?.graphBackendOptions ?? {};
  const canUseZepCloud = Boolean(graphBackendOptions.zep_cloud);
  const canUseNeo4j = Boolean(graphBackendOptions.neo4j);
  const canUseOracle = Boolean(graphBackendOptions.oracle);
  const hasAnyGraphBackendOption = canUseZepCloud || canUseNeo4j || canUseOracle;
  const latencyLabel = useMemo(() => {
    if (!Number.isFinite(backendHealth.latencyMs)) return "";
    return `${backendHealth.latencyMs} ms`;
  }, [backendHealth.latencyMs]);
  const backendStatusText = useMemo(() => {
    return latencyLabel ? `${backendHealth.url} (${latencyLabel})` : backendHealth.url;
  }, [backendHealth.url, latencyLabel]);
  const backendStatusTitle = useMemo(() => {
    if (backendHealth.loading) return `Checking ${backendStatusText}`;
    return backendHealth.online ? `Online: ${backendStatusText}` : `Offline: ${backendStatusText}`;
  }, [backendHealth.loading, backendHealth.online, backendStatusText]);

  const hasSelectedProject = useMemo(
    () => projectCatalog.items.some((project) => project.project_id === form.projectId),
    [projectCatalog.items, form.projectId],
  );

  const resolvePreferredGraphBackend = () => {
    if (canUseZepCloud) return "zep_cloud";
    if (canUseNeo4j) return "neo4j";
    if (canUseOracle) return "oracle";
    return "zep_cloud";
  };

  const goToWorkspaceHome = () => {
    if (typeof onNavigate === "function") {
      onNavigate("/");
      return;
    }
    if (typeof window !== "undefined") {
      window.location.assign(`${window.location.origin}/`);
    }
  };

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

  const openNewProjectModal = () => {
    setNewProjectGraphBackend(resolvePreferredGraphBackend());
    setNewProjectModalOpen(true);
  };

  const closeNewProjectModal = () => {
    setNewProjectModalOpen(false);
  };

  const confirmNewProjectBackend = async () => {
    await switchProject("", "", { graphBackend: newProjectGraphBackend });
    closeNewProjectModal();
  };

  return (
    <>
      <header className="topbar">
      <button className="brand brand-link-btn" type="button" onClick={goToWorkspaceHome} title="Go to home">
        z_graph
      </button>

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
                  Category Label
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
              if (selectedProjectId === NEW_PROJECT_OPTION_VALUE) {
                event.target.value = form.projectId;
                openNewProjectModal();
                return;
              }
              if (!selectedProjectId) {
                event.target.value = form.projectId;
                openNewProjectModal();
                return;
              }
              const selectedProject = projectCatalog.items.find(
                (project) => project.project_id === selectedProjectId,
              );
              switchProject(selectedProjectId, selectedProject?.project_workspace_id ?? "");
            }}
            disabled={projectCatalog.loading}
            title="Switch project"
          >
            <option value="">
              {projectCatalog.loading ? "Loading projects..." : "Select project..."}
            </option>
            <option value={NEW_PROJECT_OPTION_VALUE}>+ New Project</option>
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
          {backendStatusText}
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
      {newProjectModalOpen && (
        <div className="new-project-backend-modal-overlay">
          <div className="new-project-backend-modal" role="dialog" aria-modal="true">
            <div className="new-project-backend-modal-head">
              <h3>Select Graph Backend</h3>
            </div>
            <p className="new-project-backend-modal-note">
              Choose backend before creating a new project.
            </p>
            <label className={`new-project-backend-option ${!canUseZepCloud ? "disabled" : ""}`}>
              <input
                type="radio"
                name="new-project-graph-backend"
                value="zep_cloud"
                checked={newProjectGraphBackend === "zep_cloud"}
                disabled={!canUseZepCloud}
                onChange={(event) => setNewProjectGraphBackend(event.target.value)}
              />
              <span>zep_cloud</span>
            </label>
            <label className={`new-project-backend-option ${!canUseNeo4j ? "disabled" : ""}`}>
              <input
                type="radio"
                name="new-project-graph-backend"
                value="neo4j"
                checked={newProjectGraphBackend === "neo4j"}
                disabled={!canUseNeo4j}
                onChange={(event) => setNewProjectGraphBackend(event.target.value)}
              />
              <span>neo4j</span>
            </label>
            <label className={`new-project-backend-option ${!canUseOracle ? "disabled" : ""}`}>
              <input
                type="radio"
                name="new-project-graph-backend"
                value="oracle"
                checked={newProjectGraphBackend === "oracle"}
                disabled={!canUseOracle}
                onChange={(event) => setNewProjectGraphBackend(event.target.value)}
              />
              <span>oracle</span>
            </label>
            {!hasAnyGraphBackendOption && (
              <p className="status-line warning">
                No graph backend is configured. Set environment variables first.
              </p>
            )}
            <div className="new-project-backend-modal-actions">
              <button className="secondary-btn" type="button" onClick={closeNewProjectModal}>
                Cancel
              </button>
              <button
                className="action-btn"
                type="button"
                onClick={confirmNewProjectBackend}
                disabled={!hasAnyGraphBackendOption}
              >
                Continue
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
