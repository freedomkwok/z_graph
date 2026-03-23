import { useEffect, useRef, useState } from "react";

import { useTaskStore } from "./taskStore";

const SYSTEM_PANEL_HEIGHT_KEY = "zep_graph.system_panel_height";
const SYSTEM_PANEL_COLLAPSED_KEY = "zep_graph.system_panel_collapsed";
const MIN_SYSTEM_PANEL_HEIGHT = 90;
const DEFAULT_SYSTEM_PANEL_HEIGHT = 150;
const MAX_SYSTEM_PANEL_HEIGHT = 420;

const statusClass = (status) => {
  switch (status) {
    case "success":
      return "ok";
    case "error":
      return "error";
    case "running":
      return "running";
    default:
      return "idle";
  }
};

const clampSystemPanelHeight = (desiredHeight, totalPanelHeight) => {
  const dynamicMax = totalPanelHeight
    ? Math.max(MIN_SYSTEM_PANEL_HEIGHT, totalPanelHeight - 220)
    : MAX_SYSTEM_PANEL_HEIGHT;
  const maxHeight = Math.min(MAX_SYSTEM_PANEL_HEIGHT, dynamicMax);
  return Math.min(Math.max(desiredHeight, MIN_SYSTEM_PANEL_HEIGHT), maxHeight);
};

export default function TaskPanel() {
  const { state, setFormField, setFiles, runOntologyGenerate, runGraphBuild, addSystemLog } =
    useTaskStore();
  const { form, ontologyTask, graphTask, systemLogs } = state;
  const logContainerRef = useRef(null);
  const rightPanelRef = useRef(null);
  const systemPanelResizeActiveRef = useRef(false);
  const panelResizeStartYRef = useRef(0);
  const panelResizeStartHeightRef = useRef(DEFAULT_SYSTEM_PANEL_HEIGHT);
  const [activeTab, setActiveTab] = useState("A");
  const [isSystemPanelResizing, setIsSystemPanelResizing] = useState(false);
  const [systemPanelHeight, setSystemPanelHeight] = useState(() => {
    const saved = Number(window.localStorage.getItem(SYSTEM_PANEL_HEIGHT_KEY));
    if (Number.isFinite(saved) && saved > 0) {
      return saved;
    }
    return DEFAULT_SYSTEM_PANEL_HEIGHT;
  });
  const [isSystemPanelCollapsed, setIsSystemPanelCollapsed] = useState(
    () => window.localStorage.getItem(SYSTEM_PANEL_COLLAPSED_KEY) === "1",
  );

  const stepBUnlocked =
    ontologyTask.status === "success" || graphTask.status === "running" || graphTask.status === "success";
  const shouldShowSystemPanel = Boolean(form.projectId) || systemLogs.length > 0;
  const isProjectCreated = Boolean(form.projectId);

  const handleOntologySubmit = async (event) => {
    event.preventDefault();
    await runOntologyGenerate();
  };

  const handleGraphTabClick = () => {
    if (!stepBUnlocked) {
      addSystemLog("Step B is locked until Step A finishes ontology generation.");
      return;
    }
    setActiveTab("B");
  };

  const startSystemPanelResize = (event) => {
    if (!shouldShowSystemPanel || isSystemPanelCollapsed) return;
    if (event.currentTarget?.setPointerCapture) {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    systemPanelResizeActiveRef.current = true;
    panelResizeStartYRef.current = event.clientY;
    panelResizeStartHeightRef.current = systemPanelHeight;
    setIsSystemPanelResizing(true);
    document.body.classList.add("dashboard-resizing");
    event.preventDefault();
  };

  useEffect(() => {
    if (!logContainerRef.current) return;
    logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
  }, [systemLogs.length, isSystemPanelCollapsed]);

  useEffect(() => {
    if (activeTab === "B" && !stepBUnlocked) {
      setActiveTab("A");
    }
  }, [activeTab, stepBUnlocked]);

  useEffect(() => {
    window.localStorage.setItem(SYSTEM_PANEL_HEIGHT_KEY, String(systemPanelHeight));
  }, [systemPanelHeight]);

  useEffect(() => {
    window.localStorage.setItem(SYSTEM_PANEL_COLLAPSED_KEY, isSystemPanelCollapsed ? "1" : "0");
  }, [isSystemPanelCollapsed]);

  useEffect(() => {
    const stopResize = () => {
      if (!systemPanelResizeActiveRef.current) return;
      systemPanelResizeActiveRef.current = false;
      setIsSystemPanelResizing(false);
      document.body.classList.remove("dashboard-resizing");
    };

    const onPointerMove = (event) => {
      if (!systemPanelResizeActiveRef.current) return;
      if ((event.buttons & 1) !== 1) {
        stopResize();
        return;
      }
      const totalPanelHeight = rightPanelRef.current?.clientHeight ?? 0;
      const deltaY = panelResizeStartYRef.current - event.clientY;
      const nextHeight = clampSystemPanelHeight(
        panelResizeStartHeightRef.current + deltaY,
        totalPanelHeight,
      );
      setSystemPanelHeight(nextHeight);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
    window.addEventListener("mouseup", stopResize);
    window.addEventListener("blur", stopResize);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
      window.removeEventListener("mouseup", stopResize);
      window.removeEventListener("blur", stopResize);
      document.body.classList.remove("dashboard-resizing");
    };
  }, []);

  return (
    <section className={`right-panel ${isSystemPanelResizing ? "dashboard-resizing-active" : ""}`} ref={rightPanelRef}>
      <div className="panel-header dark">
        <div className="panel-title">
          <span className="panel-icon">▣</span>
          Graph Build
        </div>
      </div>

      <div className="right-content">
        <div className="step-tabs">
          <button
            className={`step-tab ${activeTab === "A" ? "active" : ""}`}
            type="button"
            onClick={() => setActiveTab("A")}
          >
            Step A - Ontology
          </button>
          <button
            className={`step-tab ${activeTab === "B" ? "active" : ""} ${!stepBUnlocked ? "disabled" : ""}`}
            type="button"
            onClick={handleGraphTabClick}
          >
            Step B - Graph Build
          </button>
        </div>

        {activeTab === "A" && (
          <article className="step-card">
            <div className="card-head">
              <div>
                <p className="step-index">A</p>
                <h2>Ontology Generate</h2>
                <p className="endpoint">POST /api/ontology/generate</p>
              </div>
              <span className={`badge ${statusClass(ontologyTask.status)}`}>{ontologyTask.status}</span>
            </div>
            <p className="card-description">Upload files and generate ontology schema for the project.</p>

            <form className="form-grid" onSubmit={handleOntologySubmit}>
              <label className="field">
                <span>Simulation Requirement</span>
                <textarea
                  value={form.simulationRequirement}
                  onChange={(event) => setFormField("simulationRequirement", event.target.value)}
                  placeholder="Describe the simulation goal..."
                  rows={3}
                />
              </label>

              <label className="field">
                <span>Project Name</span>
                <input
                  value={form.projectName}
                  onChange={(event) => setFormField("projectName", event.target.value)}
                  placeholder="Project name"
                  disabled={isProjectCreated}
                />
              </label>
              {isProjectCreated && (
                <p className="field-note">Project name is locked after project creation.</p>
              )}

              <label className="field">
                <span>Additional Context (optional)</span>
                <input
                  value={form.additionalContext}
                  onChange={(event) => setFormField("additionalContext", event.target.value)}
                  placeholder="Extra instructions..."
                />
              </label>

              <label className="field">
                <span>Files</span>
                <input
                  type="file"
                  multiple
                  onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
                />
              </label>

              <button className="action-btn" type="submit" disabled={ontologyTask.status === "running"}>
                {ontologyTask.status === "running" ? "Generating..." : "Run Ontology Generate"}
              </button>
            </form>

            <p className="status-line">{ontologyTask.message}</p>
            <div className="stat-grid">
              <div className="stat-box">
                <span className="stat-value">{ontologyTask.entityTypes}</span>
                <span className="stat-label">Entity Types</span>
              </div>
              <div className="stat-box">
                <span className="stat-value">{ontologyTask.edgeTypes}</span>
                <span className="stat-label">Relation Types</span>
              </div>
              <div className="stat-box">
                <span className="stat-value">{form.projectId || "-"}</span>
                <span className="stat-label">Project ID</span>
              </div>
            </div>
          </article>
        )}

        {activeTab === "B" && (
          <article className={`step-card ${!stepBUnlocked ? "locked" : ""}`}>
            <div className="card-head">
              <div>
                <p className="step-index">B</p>
                <h2>Graph Build</h2>
                <p className="endpoint">POST /api/build</p>
              </div>
              <span className={`badge ${statusClass(graphTask.status)}`}>{graphTask.status}</span>
            </div>
            <p className="card-description">
              Build graph from generated ontology and monitor task progress.
            </p>
            {!stepBUnlocked && (
              <p className="status-line warning">Step B is locked until Step A finishes successfully.</p>
            )}

            <label className="field">
              <span>Project ID</span>
              <input
                value={form.projectId}
                onChange={(event) => setFormField("projectId", event.target.value)}
                placeholder="project_xxx"
              />
            </label>

            <button
              className="action-btn"
              type="button"
              onClick={runGraphBuild}
              disabled={graphTask.status === "running" || !stepBUnlocked}
            >
              {graphTask.status === "running" ? "Building..." : "Run Graph Build"}
            </button>

            <div className="progress-wrap">
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${graphTask.progress}%` }} />
              </div>
              <span>{graphTask.progress}%</span>
            </div>

            <p className="status-line">{graphTask.message}</p>
            <div className="stat-grid">
              <div className="stat-box">
                <span className="stat-value">{graphTask.nodeCount}</span>
                <span className="stat-label">Nodes</span>
              </div>
              <div className="stat-box">
                <span className="stat-value">{graphTask.edgeCount}</span>
                <span className="stat-label">Edges</span>
              </div>
              <div className="stat-box">
                <span className="stat-value">{graphTask.chunkCount}</span>
                <span className="stat-label">Chunks</span>
              </div>
            </div>
          </article>
        )}
      </div>

      {shouldShowSystemPanel && (
        <>
          {!isSystemPanelCollapsed && (
            <>
              <div
                className="system-panel-resizer"
                role="separator"
                aria-orientation="horizontal"
                aria-label="Resize system dashboard"
                onPointerDown={startSystemPanelResize}
              />
              <div className="system-panel" style={{ height: `${systemPanelHeight}px` }}>
                <div className="system-head">
                  <span>SYSTEM DASHBOARD</span>
                  <div className="system-head-actions">
                    <span>{form.projectId || "NO_PROJECT"}</span>
                    <button
                      className="system-toggle-btn"
                      type="button"
                      onClick={() => setIsSystemPanelCollapsed(true)}
                    >
                      Minimize
                    </button>
                  </div>
                </div>
                <div className="system-log-list" ref={logContainerRef}>
                  {systemLogs.length === 0 ? (
                    <div className="system-log-empty">No logs yet.</div>
                  ) : (
                    systemLogs.map((log, index) => (
                      <div className="system-log-line" key={`${log.time}-${index}`}>
                        <span className="system-log-time">{log.time}</span>
                        <span className="system-log-message">{log.msg}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </>
          )}

          {isSystemPanelCollapsed && (
            <div className="system-panel-collapsed">
              <span>SYSTEM DASHBOARD - {form.projectId || "NO_PROJECT"}</span>
              <button
                className="system-toggle-btn"
                type="button"
                onClick={() => setIsSystemPanelCollapsed(false)}
              >
                Resume
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
