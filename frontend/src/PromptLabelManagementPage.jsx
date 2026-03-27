import { useEffect, useState } from "react";

import TopBar from "./TopBar";
import { useTaskStore } from "./TaskStore/index";

export default function PromptLabelManagementPage({ onNavigate }) {
  const { state, fetchPromptLabels, createPromptLabel, deletePromptLabel, syncPromptLabelFromLangfuse } =
    useTaskStore();
  const [isCreateRowVisible, setIsCreateRowVisible] = useState(false);
  const [newLabelName, setNewLabelName] = useState("");
  const [pageError, setPageError] = useState("");
  const [pageNotice, setPageNotice] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [deletingLabelName, setDeletingLabelName] = useState("");
  const [syncingLabelName, setSyncingLabelName] = useState("");
  const labels = state.promptLabelCatalog.items;
  const totalLabels = state.promptLabelCatalog.totalLabels ?? labels.length;

  useEffect(() => {
    fetchPromptLabels({ syncFormLabel: false });
  }, []);

  const onCreateLabel = async () => {
    setPageError("");
    setPageNotice("");
    setIsCreating(true);
    try {
      await createPromptLabel(newLabelName);
      setNewLabelName("");
      setIsCreateRowVisible(false);
    } catch (error) {
      setPageError(String(error));
    } finally {
      setIsCreating(false);
    }
  };

  const onDeleteLabel = async (name) => {
    const confirmed = window.confirm(`Delete prompt label '${name}'?`);
    if (!confirmed) return;
    setPageError("");
    setPageNotice("");
    setDeletingLabelName(name);
    try {
      await deletePromptLabel(name);
    } catch (error) {
      setPageError(String(error));
    } finally {
      setDeletingLabelName("");
    }
  };

  const onSyncLabel = async (name) => {
    setPageError("");
    setPageNotice("");
    setSyncingLabelName(name);
    try {
      const result = await syncPromptLabelFromLangfuse(name);
      const downloadedFiles = Number(result?.downloaded_files ?? 0);
      setPageNotice(
        `Label '${name}' synced from Langfuse (${downloadedFiles} file${downloadedFiles === 1 ? "" : "s"}).`,
      );
    } catch (error) {
      setPageError(String(error));
    } finally {
      setSyncingLabelName("");
    }
  };

  return (
    <div className="app-shell">
      <TopBar currentPage="prompt-labels" onNavigate={onNavigate} />
      <main className="project-management-page">
        <section className="project-management-card">
          <div className="project-management-head">
            <h1>Prompt Label Management</h1>
            <div className="prompt-label-head-actions">
              <button
                className="icon-btn"
                type="button"
                title="Add label"
                onClick={() => {
                  setPageError("");
                  setIsCreateRowVisible(true);
                }}
              >
                +
              </button>
              <button
                className="icon-btn"
                type="button"
                title="Refresh labels"
                onClick={() => fetchPromptLabels({ syncFormLabel: false })}
              >
                ↻
              </button>
              <button
                className="action-btn"
                type="button"
                onClick={() => onNavigate?.("/")}
              >
                Open Workspace
              </button>
            </div>
          </div>
          <p className="project-management-note">
            Manage available prompt labels used by Step A generation. Labels are
            stored in project storage and reused across projects.
          </p>
          <p className="project-management-note">Total labels: {totalLabels}</p>
          {pageNotice && <p className="status-line">{pageNotice}</p>}
          {pageError && <p className="status-line warning">{pageError}</p>}

          <div className="project-table-wrap">
            <table className="project-table">
              <thead>
                <tr>
                  <th>Label Name</th>
                  <th>Used By Projects</th>
                  <th>Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {isCreateRowVisible && (
                  <tr>
                    <td>
                      <input
                        className="project-name-input"
                        value={newLabelName}
                        onChange={(event) => setNewLabelName(event.target.value)}
                        placeholder="e.g. Finance, Legal, Clinical"
                        autoFocus
                      />
                    </td>
                    <td>-</td>
                    <td>-</td>
                    <td>
                      <div className="project-actions">
                        <button
                          className="icon-btn"
                          type="button"
                          onClick={onCreateLabel}
                          disabled={isCreating}
                        >
                          {isCreating ? "..." : "Save"}
                        </button>
                        <button
                          className="icon-btn"
                          type="button"
                          onClick={() => {
                            setIsCreateRowVisible(false);
                            setNewLabelName("");
                            setPageError("");
                          }}
                          disabled={isCreating}
                        >
                          Cancel
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
                {labels.length === 0 && (
                  <tr>
                    <td colSpan={4}>No labels found.</td>
                  </tr>
                )}
                {labels.map((item) => {
                  const isDeleting = deletingLabelName === item.name;
                  const isSyncing = syncingLabelName === item.name;
                  const isProtected = String(item.name).toLowerCase() === "production";
                  return (
                    <tr key={item.name}>
                      <td>{item.name}</td>
                      <td>{item.project_count ?? 0}</td>
                      <td>{item.updated_at ?? "-"}</td>
                      <td>
                        <div className="project-actions">
                          <button
                            className="icon-btn"
                            type="button"
                            onClick={() => onSyncLabel(item.name)}
                            disabled={isSyncing}
                            title="Download prompt templates for this label from Langfuse"
                          >
                            {isSyncing ? "Syncing..." : "Edit"}
                          </button>
                          <button
                            className="danger-solid-btn"
                            type="button"
                            onClick={() => onDeleteLabel(item.name)}
                            disabled={isDeleting || isProtected || isSyncing}
                            title={
                              isProtected
                                ? "Production label is protected"
                                : "Delete label"
                            }
                          >
                            {isDeleting ? "Deleting..." : "Delete"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
