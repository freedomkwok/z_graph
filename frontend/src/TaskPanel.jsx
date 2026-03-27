import { useEffect, useRef, useState } from "react";

import { useTaskStore } from "./taskStore";

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

const normalizeTypeTag = (value) =>
  String(value ?? "")
    .trim()
    .replace(/\s+/g, " ");

const extractOntologyTypeNames = (project, key) => {
  const items = Array.isArray(project?.ontology?.[key]) ? project.ontology[key] : [];
  const names = [];
  const seen = new Set();
  for (const item of items) {
    const normalized = normalizeTypeTag(item?.name);
    if (!normalized) continue;
    const dedupeKey = normalized.toLowerCase();
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    names.push(normalized);
  }
  return names;
};

function TypeTagEditor({ title, tags, onChange, placeholder, autoFocus = false, highlighted = false }) {
  const [inputValue, setInputValue] = useState("");
  const [editingIndex, setEditingIndex] = useState(-1);
  const [editingValue, setEditingValue] = useState("");
  const addInputRef = useRef(null);
  const editInputRef = useRef(null);

  useEffect(() => {
    if (!autoFocus) return;
    addInputRef.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    if (editingIndex < 0) return;
    editInputRef.current?.focus();
    editInputRef.current?.select();
  }, [editingIndex]);

  const hasDuplicate = (nextValue, excludedIndex = -1) =>
    tags.some(
      (tag, index) =>
        index !== excludedIndex &&
        normalizeTypeTag(tag).toLowerCase() === normalizeTypeTag(nextValue).toLowerCase(),
    );

  const appendTag = () => {
    const normalized = normalizeTypeTag(inputValue);
    if (!normalized || hasDuplicate(normalized)) {
      setInputValue("");
      return;
    }
    onChange([...tags, normalized]);
    setInputValue("");
  };

  const removeTagAt = (targetIndex) => {
    onChange(tags.filter((_, index) => index !== targetIndex));
  };

  const beginTagEdit = (targetIndex) => {
    setEditingIndex(targetIndex);
    setEditingValue(tags[targetIndex] ?? "");
  };

  const commitTagEdit = () => {
    if (editingIndex < 0) return;
    const normalized = normalizeTypeTag(editingValue);
    if (!normalized) {
      removeTagAt(editingIndex);
    } else if (!hasDuplicate(normalized, editingIndex)) {
      const nextTags = [...tags];
      nextTags[editingIndex] = normalized;
      onChange(nextTags);
    }
    setEditingIndex(-1);
    setEditingValue("");
  };

  const cancelTagEdit = () => {
    setEditingIndex(-1);
    setEditingValue("");
  };

  return (
    <section className={`ontology-editor-section ${highlighted ? "focused" : ""}`}>
      <h4>{title}</h4>
      <div className="ontology-tag-editor-box" onClick={() => addInputRef.current?.focus()}>
        {tags.map((tag, index) =>
          editingIndex === index ? (
            <input
              key={`${tag}-${index}`}
              ref={editInputRef}
              className="ontology-tag-edit-input"
              value={editingValue}
              onChange={(event) => setEditingValue(event.target.value)}
              onBlur={commitTagEdit}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  commitTagEdit();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  cancelTagEdit();
                }
              }}
            />
          ) : (
            <button
              key={`${tag}-${index}`}
              className="ontology-tag-chip"
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                beginTagEdit(index);
              }}
            >
              {tag}
            </button>
          ),
        )}
        <input
          ref={addInputRef}
          className="ontology-tag-input"
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          placeholder={placeholder}
          onBlur={appendTag}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ",") {
              event.preventDefault();
              appendTag();
              return;
            }
            if (event.key === "Backspace" && !inputValue && tags.length > 0) {
              event.preventDefault();
              removeTagAt(tags.length - 1);
            }
          }}
        />
      </div>
      <p className="field-note">
        Click a tag to edit. Press Enter to save. Press Backspace on empty input to remove the last tag.
      </p>
    </section>
  );
}

export default function TaskPanel() {
  const {
    state,
    setViewMode,
    setFormField,
    setProjectPromptLabel,
    setFiles,
    runOntologyGenerate,
    runGraphBuild,
    updateProjectOntologyTypes,
    addSystemLog,
  } =
    useTaskStore();
  const { form, ontologyTask, graphTask, systemLogs, promptLabelCatalog, viewMode, currentProject } =
    state;
  const logContainerRef = useRef(null);
  const [activeStepTab, setActiveStepTab] = useState("A");
  const [activeBackendTab, setActiveBackendTab] = useState("build");
  const [ontologyEditorMode, setOntologyEditorMode] = useState("");
  const [draftEntityTypeNames, setDraftEntityTypeNames] = useState([]);
  const [draftEdgeTypeNames, setDraftEdgeTypeNames] = useState([]);
  const [savingOntologyTypes, setSavingOntologyTypes] = useState(false);
  const [ontologyEditorError, setOntologyEditorError] = useState("");

  const stepBUnlocked =
    ontologyTask.status === "success" || graphTask.status === "running" || graphTask.status === "success";
  const isProjectCreated = Boolean(form.projectId);
  const canOpenOntologyEditor = Boolean(form.projectId) && ontologyTask.status !== "running";
  const isEntityEditor = ontologyEditorMode === "entity";

  const handleOntologySubmit = async (event) => {
    event.preventDefault();
    await runOntologyGenerate();
  };

  const openOntologyEditor = (mode) => {
    if (!canOpenOntologyEditor) {
      addSystemLog("Ontology editor is available after Step A finishes.");
      return;
    }
    setOntologyEditorMode(mode);
    setDraftEntityTypeNames(extractOntologyTypeNames(currentProject, "entity_types"));
    setDraftEdgeTypeNames(extractOntologyTypeNames(currentProject, "edge_types"));
    setOntologyEditorError("");
  };

  const closeOntologyEditor = () => {
    if (savingOntologyTypes) return;
    setOntologyEditorMode("");
    setOntologyEditorError("");
  };

  const confirmOntologyEditor = async () => {
    const normalizedProjectId = String(form.projectId ?? "").trim();
    if (!normalizedProjectId) {
      setOntologyEditorError("Project ID is required to save ontology edits.");
      return;
    }

    setSavingOntologyTypes(true);
    setOntologyEditorError("");
    try {
      await updateProjectOntologyTypes(normalizedProjectId, {
        entityTypeNames: draftEntityTypeNames,
        edgeTypeNames: draftEdgeTypeNames,
      });
      setOntologyEditorMode("");
    } catch (error) {
      const message = String(error);
      setOntologyEditorError(message);
      addSystemLog(`Failed to update ontology types: ${message}`);
    } finally {
      setSavingOntologyTypes(false);
    }
  };

  const handleOntologyStatBoxKeyDown = (event, section) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openOntologyEditor(section);
  };

  const handleGraphTabClick = () => {
    if (!stepBUnlocked) {
      // addSystemLog("Step B is locked until Step A finishes ontology generation.");
      return;
    }
    setActiveStepTab("B");
  };

  useEffect(() => {
    if (!logContainerRef.current) return;
    logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
  }, [systemLogs.length, activeBackendTab]);

  useEffect(() => {
    if (activeStepTab === "B" && !stepBUnlocked) {
      setActiveStepTab("A");
    }
  }, [activeStepTab, stepBUnlocked]);

  return (
    <section className="right-panel">
      <div className="panel-header dark">
        <div className="panel-title panel-title-tabs">
          <button
            className={`panel-tab-btn ${activeBackendTab === "build" ? "active" : ""}`}
            type="button"
            onClick={() => setActiveBackendTab("build")}
          >
            <span className="panel-icon">▣</span>
            Backend
          </button>
          <button
            className={`panel-tab-btn ${activeBackendTab === "dashboard" ? "active" : ""}`}
            type="button"
            onClick={() => setActiveBackendTab("dashboard")}
          >
            <span className="panel-tab-note-icon">📝</span>
            System Dashboard
          </button>
        </div>
        {viewMode === "both" && (
          <button
            className="icon-btn"
            type="button"
            title="Collapse backend panel for full graph view"
            onClick={() => setViewMode("graph")}
          >
            ⤢
          </button>
        )}
      </div>

      <div className="right-content">
        {activeBackendTab === "build" && (
          <>
            <div className="step-tabs">
              <button
                className={`step-tab ${activeStepTab === "A" ? "active" : ""}`}
                type="button"
                onClick={() => setActiveStepTab("A")}
              >
                Step A - Ontology
              </button>
              <button
                className={`step-tab ${activeStepTab === "B" ? "active" : ""} ${!stepBUnlocked ? "disabled" : ""}`}
                type="button"
                onClick={handleGraphTabClick}
              >
                Step B - Graph Build
              </button>
            </div>

            {activeStepTab === "A" && (
              <article className="step-card">
                <div className="card-head">
                  <div>
                    <h2 className="step-title">
                      <span className="step-index-inline">A</span>
                      Ontology Generate
                    </h2>
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
                    <span>Prompt Category</span>
                    <select
                      value={form.promptLabel}
                      onChange={(event) => setProjectPromptLabel(event.target.value)}
                    >
                      {promptLabelCatalog.items.length === 0 ? (
                        <option value={form.promptLabel || "Production"}>
                          {form.promptLabel || "Production"}
                        </option>
                      ) : (
                        promptLabelCatalog.items.map((item) => (
                          <option key={item.name} value={item.name}>
                            {item.name}
                          </option>
                        ))
                      )}
                    </select>
                    <p className="field-note">
                      Prompt resolution tries selected label first, then Production, then local prompt file.
                    </p>
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

                <div className="progress-wrap">
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${ontologyTask.progress ?? 0}%` }} />
                  </div>
                  <span>{ontologyTask.progress ?? 0}%</span>
                </div>

                <p className="status-line">{ontologyTask.message}</p>
                <div className="stat-grid">
                  <div className="stat-box">
                    <span className="stat-value">{form.projectId || "-"}</span>
                    <span className="stat-label">Project ID</span>
                  </div>
                  <div
                    className={`stat-box clickable ${canOpenOntologyEditor ? "" : "disabled"}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => openOntologyEditor("entity")}
                    onKeyDown={(event) => handleOntologyStatBoxKeyDown(event, "entity")}
                    title="Open ontology type editor"
                  >
                    <span className="stat-value">{ontologyTask.entityTypes}</span>
                    <span className="stat-label">Entity Types</span>
                  </div>
                  <div
                    className={`stat-box clickable ${canOpenOntologyEditor ? "" : "disabled"}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => openOntologyEditor("relationship")}
                    onKeyDown={(event) => handleOntologyStatBoxKeyDown(event, "relationship")}
                    title="Open ontology type editor"
                  >
                    <span className="stat-value">{ontologyTask.edgeTypes}</span>
                    <span className="stat-label">Relationship Types</span>
                  </div>
                </div>
              </article>
            )}

            {activeStepTab === "B" && (
              <article className={`step-card ${!stepBUnlocked ? "locked" : ""}`}>
                <div className="card-head">
                  <div>
                    <h2 className="step-title">
                      <span className="step-index-inline">B</span>
                      Graph Build
                    </h2>
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
                  <span>Graph Name</span>
                  <input
                    value={form.graphName}
                    onChange={(event) => setFormField("graphName", event.target.value)}
                    placeholder={`Defaults to ${form.projectId || "project_id"}`}
                  />
                  <p className="field-note">
                    Uses selected Project ID ({form.projectId || "-"}) when Graph Name is empty.
                  </p>
                </label>

                <label className="field">
                  <span>Chunk Size</span>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={form.chunkSize}
                    onChange={(event) => setFormField("chunkSize", event.target.value)}
                    placeholder="500"
                  />
                </label>

                <label className="field">
                  <span>Chunk Overlap</span>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={form.chunkOverlap}
                    onChange={(event) => setFormField("chunkOverlap", event.target.value)}
                    placeholder="50"
                  />
                  <p className="field-note">Defaults: chunk size 500, overlap 50.</p>
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
          </>
        )}

        {activeBackendTab === "dashboard" && (
          <article className="dashboard-tab-card">
            <div className="dashboard-tab-head">
              <h2>System Dashboard</h2>
              <span className="dashboard-project-id">{form.projectId || "NO_PROJECT"}</span>
            </div>
            <div className="dashboard-log-list" ref={logContainerRef}>
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
          </article>
        )}
      </div>

      {Boolean(ontologyEditorMode) && (
        <div className="ontology-editor-overlay" onClick={closeOntologyEditor}>
          <article
            className="ontology-editor-panel"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={isEntityEditor ? "Entity type editor" : "Relationship type editor"}
          >
            <div className="ontology-editor-head">
              <h3>{isEntityEditor ? "Edit Entity Types" : "Edit Relationship Types"}</h3>
              <button
                className="ontology-editor-close"
                type="button"
                onClick={closeOntologyEditor}
                disabled={savingOntologyTypes}
                aria-label="Close ontology editor"
              >
                ×
              </button>
            </div>
            <p className="ontology-editor-note">
              {isEntityEditor
                ? "Update entity type names. Existing entity metadata (description, attributes, examples) is preserved for renamed entries."
                : "Update relationship type names. Existing relationship metadata (source-target pairs and attributes) is preserved for renamed entries."}
            </p>
            <div className="ontology-editor-section-list">
              {isEntityEditor ? (
                <TypeTagEditor
                  title="Entity Types"
                  tags={draftEntityTypeNames}
                  onChange={setDraftEntityTypeNames}
                  placeholder="Add entity type and press Enter"
                  autoFocus
                  highlighted
                />
              ) : (
                <TypeTagEditor
                  title="Relationship Types"
                  tags={draftEdgeTypeNames}
                  onChange={setDraftEdgeTypeNames}
                  placeholder="Add relationship type and press Enter"
                  autoFocus
                  highlighted
                />
              )}
            </div>
            {ontologyEditorError && <p className="ontology-editor-error">{ontologyEditorError}</p>}
            <div className="ontology-editor-actions">
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={closeOntologyEditor}
                disabled={savingOntologyTypes}
              >
                Cancel
              </button>
              <button className="action-btn" type="button" onClick={confirmOntologyEditor} disabled={savingOntologyTypes}>
                {savingOntologyTypes ? "Saving..." : "Confirm"}
              </button>
            </div>
          </article>
        </div>
      )}
    </section>
  );
}
