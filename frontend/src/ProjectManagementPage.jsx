import { useEffect, useMemo, useState } from "react";

import TopBar from "./TopBar";
import { useTaskStore } from "./taskStore";

function formatProjectShortId(projectId) {
  const normalized = String(projectId ?? "").trim();
  if (!normalized) return "--------";
  return normalized.slice(-8);
}

export default function ProjectManagementPage({ onNavigate }) {
  const { state, fetchProjects, switchProject, updateProjectName, deleteProject, addSystemLog } =
    useTaskStore();
  const [editingNames, setEditingNames] = useState({});
  const [savingProjectId, setSavingProjectId] = useState("");
  const [deletingProjectId, setDeletingProjectId] = useState("");
  const [pageError, setPageError] = useState("");
  const projects = state.projectCatalog.items;

  useEffect(() => {
    fetchProjects(undefined, false);
  }, []);

  useEffect(() => {
    const nextNames = {};
    for (const project of projects) {
      nextNames[project.project_id] = String(project.name ?? "");
    }
    setEditingNames(nextNames);
  }, [projects]);

  const hasProjects = projects.length > 0;
  const sortedProjects = useMemo(() => [...projects], [projects]);

  const onSaveName = async (projectId) => {
    const nextName = String(editingNames[projectId] ?? "").trim();
    if (!nextName) {
      setPageError("Project name is required.");
      return;
    }
    setPageError("");
    setSavingProjectId(projectId);
    try {
      await updateProjectName(projectId, nextName);
    } catch (error) {
      setPageError(String(error));
      addSystemLog(`Project rename failed: ${String(error)}`);
    } finally {
      setSavingProjectId("");
    }
  };

  const onDeleteProject = async (projectId) => {
    const confirmed = window.confirm(
      `Delete project ${projectId}? This will remove project metadata and uploaded files.`,
    );
    if (!confirmed) return;
    setPageError("");
    setDeletingProjectId(projectId);
    try {
      await deleteProject(projectId);
    } catch (error) {
      setPageError(String(error));
      addSystemLog(`Project delete failed: ${String(error)}`);
    } finally {
      setDeletingProjectId("");
    }
  };

  return (
    <div className="app-shell">
      <TopBar currentPage="projects" onNavigate={onNavigate} />
      <main className="project-management-page">
        <section className="project-management-card">
          <div className="project-management-head">
            <h1>Project Management</h1>
            <button className="action-btn" type="button" onClick={() => fetchProjects(undefined, false)}>
              Refresh
            </button>
          </div>
          <p className="project-management-note">
            Manage projects saved in storage. Rename projects, delete old projects, or open one to resume.
          </p>
          {pageError && <p className="status-line warning">{pageError}</p>}
          {!hasProjects ? (
            <p className="status-line">No projects found.</p>
          ) : (
            <div className="project-table-wrap">
              <table className="project-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Project ID</th>
                    <th>Status</th>
                    <th>Updated</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedProjects.map((project) => {
                    const isSaving = savingProjectId === project.project_id;
                    const isDeleting = deletingProjectId === project.project_id;
                    return (
                      <tr key={project.project_id}>
                        <td>
                          <input
                            className="project-name-input"
                            value={editingNames[project.project_id] ?? ""}
                            onChange={(event) =>
                              setEditingNames((prev) => ({
                                ...prev,
                                [project.project_id]: event.target.value,
                              }))
                            }
                            disabled={isSaving || isDeleting}
                          />
                        </td>
                        <td className="project-id-cell" title={project.project_id}>
                          {formatProjectShortId(project.project_id)}
                        </td>
                        <td>{project.status ?? "-"}</td>
                        <td>{project.updated_at ?? "-"}</td>
                        <td>
                          <div className="project-actions">
                            <button
                              className="icon-btn"
                              type="button"
                              onClick={() => onSaveName(project.project_id)}
                              disabled={isSaving || isDeleting}
                              title="Save project name"
                            >
                              {isSaving ? "…" : "Save"}
                            </button>
                            <button
                              className="icon-btn"
                              type="button"
                              onClick={async () => {
                                await switchProject(project.project_id);
                                onNavigate?.("/");
                              }}
                              disabled={isSaving || isDeleting}
                              title="Open project in workspace"
                            >
                              Open
                            </button>
                            <button
                              className="icon-btn danger-btn"
                              type="button"
                              onClick={() => onDeleteProject(project.project_id)}
                              disabled={isSaving || isDeleting}
                              title="Delete project"
                            >
                              {isDeleting ? "…" : "Delete"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
