import { useEffect, useState } from "react";

import TopBar from "./TopBar";
import { useTaskStore } from "./taskStore";

export default function PromptLabelManagementPage({ onNavigate }) {
  const { state, fetchPromptLabels, createPromptLabel, deletePromptLabel } = useTaskStore();
  const [isCreateRowVisible, setIsCreateRowVisible] = useState(false);
  const [newLabelName, setNewLabelName] = useState("");
  const [pageError, setPageError] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [deletingLabelName, setDeletingLabelName] = useState("");
  const labels = state.promptLabelCatalog.items;

  useEffect(() => {
    fetchPromptLabels({ syncFormLabel: false });
  }, []);

  const onCreateLabel = async () => {
    setPageError("");
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
    setDeletingLabelName(name);
    try {
      await deletePromptLabel(name);
    } catch (error) {
      setPageError(String(error));
    } finally {
      setDeletingLabelName("");
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
                  const isProtected = String(item.name).toLowerCase() === "production";
                  return (
                    <tr key={item.name}>
                      <td>{item.name}</td>
                      <td>{item.project_count ?? 0}</td>
                      <td>{item.updated_at ?? "-"}</td>
                      <td>
                        <button
                          className="danger-solid-btn"
                          type="button"
                          onClick={() => onDeleteLabel(item.name)}
                          disabled={isDeleting || isProtected}
                          title={
                            isProtected
                              ? "Production label is protected"
                              : "Delete label"
                          }
                        >
                          {isDeleting ? "Deleting..." : "Delete"}
                        </button>
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
