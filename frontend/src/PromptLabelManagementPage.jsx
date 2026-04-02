import { useEffect, useState } from "react";

import TopBar from "./TopBar";
import EditableStringListEditor from "./components/EditableStringListEditor";
import { useTaskStore } from "./TaskStore/index";

const PROMPT_LABEL_TYPE_FIELDS = [
  "individual",
  "individual_exception",
  "organization",
  "organization_exception",
  "relationship",
  "relationship_exception",
];

const PROMPT_LABEL_FIELD_PAIR_MAP = {
  individual: "individual_exception",
  individual_exception: "individual",
  organization: "organization_exception",
  organization_exception: "organization",
  relationship: "relationship_exception",
  relationship_exception: "relationship",
};

const createEmptyPromptLabelTypeLists = () => ({
  individual: [],
  individual_exception: [],
  organization: [],
  organization_exception: [],
  relationship: [],
  relationship_exception: [],
});

const createPromptLabelTypeCollapseState = () => ({
  individual: false,
  individual_exception: false,
  organization: false,
  organization_exception: false,
  relationship: false,
  relationship_exception: false,
});

const normalizePromptLabelTypeListValues = (values) => {
  const nextValues = [];
  const seen = new Set();
  for (const value of Array.isArray(values) ? values : []) {
    const normalized = String(value ?? "").trim();
    if (!normalized) continue;
    const dedupeKey = normalized.toLowerCase();
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    nextValues.push(normalized);
  }
  return nextValues;
};

const normalizePromptLabelTypeListsPayload = (value) => ({
  individual: normalizePromptLabelTypeListValues(value?.individual),
  individual_exception: normalizePromptLabelTypeListValues(value?.individual_exception),
  organization: normalizePromptLabelTypeListValues(value?.organization),
  organization_exception: normalizePromptLabelTypeListValues(value?.organization_exception),
  relationship: normalizePromptLabelTypeListValues(value?.relationship),
  relationship_exception: normalizePromptLabelTypeListValues(value?.relationship_exception),
});

const removeCrossListDuplicates = (typeName, values, allTypeLists) => {
  const pairedField = PROMPT_LABEL_FIELD_PAIR_MAP[typeName];
  if (!pairedField) {
    return { values, removed: [] };
  }
  const pairedValues = normalizePromptLabelTypeListValues(allTypeLists?.[pairedField]);
  const pairedKeys = new Set(pairedValues.map((item) => item.toLowerCase()));
  const kept = [];
  const removed = [];
  for (const value of Array.isArray(values) ? values : []) {
    const key = String(value ?? "").trim().toLowerCase();
    if (!key) continue;
    if (pairedKeys.has(key)) {
      removed.push(value);
      continue;
    }
    kept.push(value);
  }
  return { values: kept, removed };
};

export default function PromptLabelManagementPage({ onNavigate }) {
  const {
    state,
    fetchPromptLabels,
    createPromptLabel,
    deletePromptLabel,
    syncPromptLabelFromLangfuse,
    getPromptLabelTypeLists,
    updatePromptLabelTypeLists,
  } = useTaskStore();
  const [pageError, setPageError] = useState("");
  const [pageNotice, setPageNotice] = useState("");
  const [deletingLabelName, setDeletingLabelName] = useState("");
  const [promptLabelEditor, setPromptLabelEditor] = useState({
    open: false,
    labelName: "",
    isNewLabel: false,
    loadingTypes: false,
    syncing: false,
    savingTypes: false,
    typesDraftTouched: false,
    typeLists: createEmptyPromptLabelTypeLists(),
    collapsedTypeSections: createPromptLabelTypeCollapseState(),
    notice: "",
    error: "",
  });
  const labels = state.promptLabelCatalog.items;
  const totalLabels = state.promptLabelCatalog.totalLabels ?? labels.length;
  const editingPromptLabelMeta = labels.find(
    (item) =>
      String(item?.name ?? "").trim().toLowerCase() ===
      String(promptLabelEditor.labelName ?? "").trim().toLowerCase(),
  );

  useEffect(() => {
    fetchPromptLabels({ syncFormLabel: false });
  }, []);

  const onDeleteLabel = async (name) => {
    const confirmed = window.confirm(`Delete category label '${name}'?`);
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

  const openPromptLabelEditor = (labelName) => {
    const normalized = String(labelName ?? "").trim();
    if (!normalized) return;
    setPromptLabelEditor({
      open: true,
      labelName: normalized,
      isNewLabel: false,
      loadingTypes: true,
      syncing: false,
      savingTypes: false,
      typesDraftTouched: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      collapsedTypeSections: createPromptLabelTypeCollapseState(),
      notice: "",
      error: "",
    });
  };

  const openNewPromptLabelEditor = () => {
    setPageError("");
    setPromptLabelEditor({
      open: true,
      labelName: "",
      isNewLabel: true,
      loadingTypes: false,
      syncing: false,
      savingTypes: false,
      typesDraftTouched: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      collapsedTypeSections: createPromptLabelTypeCollapseState(),
      notice: "",
      error: "",
    });
  };

  const openClonePromptLabelEditor = async (sourceLabelName) => {
    const sourceLabel = String(sourceLabelName ?? "").trim();
    if (!sourceLabel) return;
    setPageError("");
    setPromptLabelEditor({
      open: true,
      labelName: "",
      isNewLabel: true,
      loadingTypes: true,
      syncing: false,
      savingTypes: false,
      typesDraftTouched: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      collapsedTypeSections: createPromptLabelTypeCollapseState(),
      notice: "",
      error: "",
    });
    try {
      const sourceTypes = await getPromptLabelTypeLists(sourceLabel);
      setPromptLabelEditor((current) => ({
        ...current,
        loadingTypes: false,
        typesDraftTouched: false,
        typeLists: normalizePromptLabelTypeListsPayload(sourceTypes?.types),
        notice: `Cloned defaults from '${sourceLabel}'. Enter a new label name and save.`,
      }));
    } catch (error) {
      setPromptLabelEditor((current) => ({
        ...current,
        loadingTypes: false,
        notice: "",
        error: String(error),
      }));
    }
  };

  const closePromptLabelEditor = () => {
    if (promptLabelEditor.loadingTypes || promptLabelEditor.syncing || promptLabelEditor.savingTypes) return;
    setPromptLabelEditor({
      open: false,
      labelName: "",
      isNewLabel: false,
      loadingTypes: false,
      syncing: false,
      savingTypes: false,
      typesDraftTouched: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      collapsedTypeSections: createPromptLabelTypeCollapseState(),
      notice: "",
      error: "",
    });
  };

  const updatePromptLabelTypeListDraft = (typeName, nextValues) => {
    if (!PROMPT_LABEL_TYPE_FIELDS.includes(typeName)) return;
    setPromptLabelEditor((current) => {
      const normalizedNext = normalizePromptLabelTypeListValues(nextValues);
      const filtered = removeCrossListDuplicates(typeName, normalizedNext, current.typeLists);
      const pairedField = PROMPT_LABEL_FIELD_PAIR_MAP[typeName];
      const pairedLabel = String(pairedField ?? "")
        .replace(/_/g, " ")
        .replace(/\b\w/g, (char) => char.toUpperCase());
      return {
        ...current,
        typesDraftTouched: true,
        typeLists: {
          ...current.typeLists,
          [typeName]: filtered.values,
        },
        notice:
          filtered.removed.length > 0
            ? `Ignored duplicate value(s) already present in ${pairedLabel}.`
            : "",
        error: "",
      };
    });
  };

  const togglePromptLabelTypeSectionCollapse = (typeName) => {
    if (!PROMPT_LABEL_TYPE_FIELDS.includes(typeName)) return;
    setPromptLabelEditor((current) => ({
      ...current,
      collapsedTypeSections: {
        ...createPromptLabelTypeCollapseState(),
        ...current.collapsedTypeSections,
        [typeName]: !current?.collapsedTypeSections?.[typeName],
      },
    }));
  };

  const savePromptLabelTypeLists = async () => {
    const labelName = String(promptLabelEditor.labelName ?? "").trim();
    if (!labelName) {
      setPromptLabelEditor((current) => ({
        ...current,
        error: "Label name is required.",
        notice: "",
      }));
      return;
    }
    const existingLabels = new Set(labels.map((item) => String(item?.name ?? "").trim().toLowerCase()).filter(Boolean));
    if (promptLabelEditor.isNewLabel && existingLabels.has(labelName.toLowerCase())) {
      setPromptLabelEditor((current) => ({
        ...current,
        error: `Category label '${labelName}' already exists. Choose another name.`,
        notice: "",
      }));
      return;
    }

    setPromptLabelEditor((current) => ({
      ...current,
      savingTypes: true,
      error: "",
      notice: "",
    }));
    try {
      if (promptLabelEditor.isNewLabel) {
        await createPromptLabel(labelName);
      }
      const payload = normalizePromptLabelTypeListsPayload(promptLabelEditor.typeLists);
      await updatePromptLabelTypeLists(labelName, payload);
      await fetchPromptLabels({ syncFormLabel: false });
      setPromptLabelEditor({
        open: false,
        labelName: "",
        isNewLabel: false,
        loadingTypes: false,
        syncing: false,
        savingTypes: false,
        typesDraftTouched: false,
        typeLists: createEmptyPromptLabelTypeLists(),
        collapsedTypeSections: createPromptLabelTypeCollapseState(),
        notice: "",
        error: "",
      });
      setPageNotice(
        promptLabelEditor.isNewLabel
          ? `Created category label: ${labelName}`
          : `Saved category label: ${labelName}`,
      );
    } catch (error) {
      setPromptLabelEditor((current) => ({
        ...current,
        savingTypes: false,
        notice: "",
        error: String(error),
      }));
    }
  };

  const revertPromptLabelEditorToDefault = async () => {
    if (promptLabelEditor.loadingTypes || promptLabelEditor.syncing || promptLabelEditor.savingTypes) return;
    setPromptLabelEditor((current) => ({
      ...current,
      loadingTypes: true,
      notice: "",
      error: "",
    }));
    try {
      const result = await getPromptLabelTypeLists("Production");
      setPromptLabelEditor((current) => ({
        ...current,
        loadingTypes: false,
        typesDraftTouched: false,
        typeLists: normalizePromptLabelTypeListsPayload(result?.types),
        notice: "Reverted to Production defaults. Save to apply changes.",
        error: "",
      }));
    } catch (error) {
      setPromptLabelEditor((current) => ({
        ...current,
        loadingTypes: false,
        notice: "",
        error: String(error),
      }));
    }
  };

  const syncNewPromptLabelFromDefault = async () => {
    if (!promptLabelEditor.isNewLabel) return;
    if (promptLabelEditor.loadingTypes || promptLabelEditor.syncing || promptLabelEditor.savingTypes) return;
    setPromptLabelEditor((current) => ({
      ...current,
      syncing: true,
      notice: "",
      error: "",
    }));
    try {
      await syncPromptLabelFromLangfuse("Production");
      const result = await getPromptLabelTypeLists("Production");
      setPromptLabelEditor((current) => ({
        ...current,
        syncing: false,
        typesDraftTouched: false,
        typeLists: normalizePromptLabelTypeListsPayload(result?.types),
        notice: "Synced from Production defaults.",
        error: "",
      }));
    } catch (error) {
      setPromptLabelEditor((current) => ({
        ...current,
        syncing: false,
        notice: "",
        error: String(error),
      }));
    }
  };

  useEffect(() => {
    const labelName = String(promptLabelEditor.labelName ?? "").trim();
    if (!promptLabelEditor.open || promptLabelEditor.isNewLabel || !labelName) return undefined;

    let cancelled = false;
    getPromptLabelTypeLists(labelName)
      .then((result) => {
        if (cancelled) return;
        setPromptLabelEditor((current) => {
          const currentLabel = String(current.labelName ?? "").trim().toLowerCase();
          if (!current.open || currentLabel !== labelName.toLowerCase()) return current;
          return {
            ...current,
            loadingTypes: false,
            typeLists: current.typesDraftTouched
              ? current.typeLists
              : normalizePromptLabelTypeListsPayload(result?.types),
            error: "",
          };
        });
      })
      .catch((error) => {
        if (cancelled) return;
        setPromptLabelEditor((current) => ({
          ...current,
          loadingTypes: false,
          error: String(error),
        }));
      });

    return () => {
      cancelled = true;
    };
  }, [promptLabelEditor.open, promptLabelEditor.isNewLabel, promptLabelEditor.labelName]);

  return (
    <div className="app-shell">
      <TopBar currentPage="prompt-labels" onNavigate={onNavigate} />
      <main className="project-management-page">
        <section className="project-management-card">
          <div className="project-management-head">
            <h1>Category Label[Production]</h1>
            <div className="prompt-label-head-actions">
              <button
                className="icon-btn"
                type="button"
                title="Add label"
                onClick={() => {
                  openNewPromptLabelEditor();
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
            </div>
          </div>
          <p className="project-management-note">
            Manage available category labels used by Step A generation. Labels are
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
                        <div className="project-actions">
                          <button
                            className="icon-btn"
                            type="button"
                            onClick={() => openClonePromptLabelEditor(item.name)}
                            title="Clone this label into a new one"
                          >
                            Clone
                          </button>
                          <button
                            className="icon-btn"
                            type="button"
                            onClick={() => openPromptLabelEditor(item.name)}
                            title="Edit label type lists"
                          >
                            Edit
                          </button>
                          {!isProtected && (
                            <button
                              className="danger-solid-btn"
                              type="button"
                              onClick={() => onDeleteLabel(item.name)}
                              disabled={isDeleting}
                              title="Delete label"
                            >
                              {isDeleting ? "Deleting..." : "Delete"}
                            </button>
                          )}
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
      {promptLabelEditor.open && (
        <div className="prompt-label-editor-overlay">
          <article
            className="prompt-label-editor-panel"
            role="dialog"
            aria-modal="true"
            aria-label="Category label editor"
          >
            <div className="ontology-editor-head">
              <h3>{promptLabelEditor.isNewLabel ? "Add New Label" : "Save Label"}</h3>
              <button
                className="ontology-editor-close"
                type="button"
                onClick={closePromptLabelEditor}
                disabled={promptLabelEditor.loadingTypes || promptLabelEditor.syncing || promptLabelEditor.savingTypes}
                aria-label="Close category label editor"
              >
                ×
              </button>
            </div>
            <div className="prompt-label-editor-top-meta">
              <div className="prompt-label-editor-meta-card">
                <span className="prompt-label-editor-meta-label">Used By Projects</span>
                <span className="prompt-label-editor-meta-number">
                  {promptLabelEditor.isNewLabel ? 0 : Number(editingPromptLabelMeta?.project_count ?? 0)}
                </span>
              </div>
              <div className="prompt-label-editor-meta-card">
                <span className="prompt-label-editor-meta-label">Updated At</span>
                <span className="prompt-label-editor-meta-value">
                  {promptLabelEditor.isNewLabel ? "-" : editingPromptLabelMeta?.updated_at ?? "-"}
                </span>
              </div>
            </div>
            <p className="ontology-editor-note">
              {promptLabelEditor.isNewLabel
                ? "Create a new label from empty values, clone values, or sync from Production defaults."
                : "Edit list values for this label. Use Revert to Default to load Production values."}
            </p>
            <div className="ontology-property-body">
              <div className="ontology-property-row ontology-inline-field">
                <span className="ontology-property-row-label">Label Name:</span>
                <div className="ontology-property-row-editor">
                  <input
                    value={promptLabelEditor.labelName}
                    readOnly={!promptLabelEditor.isNewLabel}
                    onChange={(event) =>
                      setPromptLabelEditor((current) => ({
                        ...current,
                        labelName: String(event.target.value ?? ""),
                        error: "",
                        notice: "",
                      }))
                    }
                    placeholder={promptLabelEditor.isNewLabel ? "Enter new label name" : ""}
                  />
                </div>
              </div>

              {promptLabelEditor.loadingTypes && <p className="field-note">Loading label types...</p>}

              {[
                {
                  field: "individual",
                  label: "Individual",
                  placeholder: "Add individual type and press Enter",
                },
                {
                  field: "individual_exception",
                  label: "Individual Exception",
                  placeholder: "Add fallback individual type and press Enter",
                },
                {
                  field: "organization",
                  label: "Organization",
                  placeholder: "Add organization type and press Enter",
                },
                {
                  field: "organization_exception",
                  label: "Organization Exception",
                  placeholder: "Add fallback organization type and press Enter",
                },
                {
                  field: "relationship",
                  label: "Relationship",
                  placeholder: "Add relationship type and press Enter",
                },
                {
                  field: "relationship_exception",
                  label: "Relationship Exception",
                  placeholder: "Add fallback relationship type and press Enter",
                },
              ].map((row) => {
                const disabled = promptLabelEditor.syncing || promptLabelEditor.savingTypes;
                const isCollapsed = Boolean(promptLabelEditor?.collapsedTypeSections?.[row.field]);
                const collapsedCount = Array.isArray(promptLabelEditor.typeLists?.[row.field])
                  ? promptLabelEditor.typeLists[row.field].length
                  : 0;
                return (
                  <div
                    key={row.field}
                    className={`ontology-property-row align-top has-collapse ${isCollapsed ? "collapsed" : ""}`}
                  >
                    <span className="ontology-property-row-label">
                      {row.label}:
                    </span>
                    <div className="ontology-property-row-editor">
                      {isCollapsed ? (
                        <p className="field-note ontology-property-collapsed-note">
                          Total: {collapsedCount} item{collapsedCount === 1 ? "" : "s"}
                        </p>
                      ) : (
                        <EditableStringListEditor
                          values={promptLabelEditor.typeLists?.[row.field] ?? []}
                          onChange={(nextValues) => updatePromptLabelTypeListDraft(row.field, nextValues)}
                          placeholder={row.placeholder}
                          disabled={disabled}
                          showEditTools
                        />
                      )}
                    </div>
                    <span
                      className={`ontology-property-row-collapse-indicator ${isCollapsed ? "collapsed" : "expanded"} ${disabled ? "disabled" : ""}`}
                      role="button"
                      tabIndex={disabled ? -1 : 0}
                      onClick={() => {
                        if (disabled) return;
                        togglePromptLabelTypeSectionCollapse(row.field);
                      }}
                      onKeyDown={(event) => {
                        if (disabled) return;
                        if (event.key !== "Enter" && event.key !== " ") return;
                        event.preventDefault();
                        togglePromptLabelTypeSectionCollapse(row.field);
                      }}
                      aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${row.label}`}
                      title={isCollapsed ? "Expand section" : "Collapse section"}
                    >
                      {isCollapsed ? "+" : "-"}
                    </span>
                  </div>
                );
              })}
            </div>
            {promptLabelEditor.notice && <p className="status-line">{promptLabelEditor.notice}</p>}
            {promptLabelEditor.error && <p className="ontology-editor-error">{promptLabelEditor.error}</p>}
            <div className="ontology-editor-actions">
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={closePromptLabelEditor}
                disabled={promptLabelEditor.loadingTypes || promptLabelEditor.syncing || promptLabelEditor.savingTypes}
              >
                Cancel
              </button>
              {promptLabelEditor.isNewLabel && (
                <button
                  className="ontology-editor-cancel-btn"
                  type="button"
                  onClick={syncNewPromptLabelFromDefault}
                  disabled={
                    promptLabelEditor.loadingTypes || promptLabelEditor.syncing || promptLabelEditor.savingTypes
                  }
                >
                  {promptLabelEditor.syncing ? "Syncing..." : "Sync From Default"}
                </button>
              )}
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={revertPromptLabelEditorToDefault}
                disabled={promptLabelEditor.loadingTypes || promptLabelEditor.syncing || promptLabelEditor.savingTypes}
              >
                Revert to Default
              </button>
              <button
                className="action-btn"
                type="button"
                onClick={savePromptLabelTypeLists}
                disabled={
                  promptLabelEditor.syncing ||
                  promptLabelEditor.savingTypes ||
                  !String(promptLabelEditor.labelName ?? "").trim()
                }
              >
                {promptLabelEditor.savingTypes
                  ? promptLabelEditor.isNewLabel
                    ? "Creating..."
                    : "Saving..."
                  : promptLabelEditor.isNewLabel
                    ? "Create Label"
                    : "Save Types"}
              </button>
            </div>
          </article>
        </div>
      )}
    </div>
  );
}
