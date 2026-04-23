import { useRef } from "react";

import EditableStringListEditor from "../../components/EditableStringListEditor";
import { renderMarkdownToHtml } from "../markdownPreview";

const PROMPT_LABEL_TYPE_ROWS = [
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
];

export default function PromptLabelEditorModal({
  promptLabelEditor,
  editingPromptLabelMeta,
  activeTopPromptLabelEditorTab,
  activePromptLabelEditorTab,
  activeNodeEdgesEditorTab,
  isPromptTemplateTab,
  promptLabelEditorTabItems,
  nodeEdgesEditorTabItems,
  canGenerateFromLlm,
  generateFromLlmHelpText,
  onClose,
  onLabelNameChange,
  onTabChange,
  onNodeEdgesTabChange,
  onPromptTemplateDraftChange,
  onPromptTemplateHeightChange,
  onPromptTemplatePreviewToggle,
  onUpdatePromptTemplate,
  canUpdatePromptTemplate,
  isUpdatingPromptTemplate,
  onTypeListChange,
  onToggleTypeSectionCollapse,
  onRevertToDefault,
  onSyncFromDefault,
  onGenerateFromLlm,
  onKeepRemainingOnGenerateChange,
  onSave,
}) {
  if (!promptLabelEditor?.open) return null;
  const isNodeEdgesTab = String(activeTopPromptLabelEditorTab ?? "").trim() === "node_edges";
  const isNodeEdgesContentTab = String(activePromptLabelEditorTab ?? "").trim() === "node_edges_content";
  const isPromptTemplateEditorTab = isPromptTemplateTab(activePromptLabelEditorTab);
  const promptTemplateTextareaRef = useRef(null);
  const footerActionsDisabled =
    promptLabelEditor.syncing ||
    promptLabelEditor.loadingPromptTemplate ||
    promptLabelEditor.savingTypes ||
    promptLabelEditor.generatingFromLlm ||
    Boolean(String(promptLabelEditor.updatingPromptTemplateKey ?? "").trim());
  const disableGenerateFromLlm = footerActionsDisabled || !canGenerateFromLlm;

  return (
    <div className="prompt-label-editor-overlay">
      <article
        className={`prompt-label-editor-panel ${promptLabelEditor.isNewLabel ? "is-new-label" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Category label editor"
      >
        <div className="ontology-editor-head">
          <h3>{promptLabelEditor.isNewLabel ? "Add New Label" : "Save Label"}</h3>
          <button
            className="ontology-editor-close"
            type="button"
            onClick={onClose}
            disabled={
              promptLabelEditor.syncing ||
              promptLabelEditor.loadingPromptTemplate ||
              promptLabelEditor.savingTypes ||
              promptLabelEditor.generatingFromLlm ||
              Boolean(String(promptLabelEditor.updatingPromptTemplateKey ?? "").trim())
            }
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
          {activePromptLabelEditorTab === "ontology_prompt"
            ? "Edit ONTOLOGY_SYSTEM_PROMPT.md for this label. If a label-specific prompt is missing, Production defaults are loaded."
            : activePromptLabelEditorTab === "ontology_output_extraction"
              ? "Edit Ontology Output prompt for this label. If a label-specific prompt is missing, Production defaults are loaded."
              : activePromptLabelEditorTab === "entity_edge_generator_prompt"
                ? "Edit ENTITY_EDGE_GENERATOR.md used by Generate From LLM. Production defaults are loaded when unavailable."
              : promptLabelEditor.isNewLabel
                ? "Create a new category label. Nothing is saved until you click Create Label."
                : "Edit Node/Edges extraction lists for this label. Generate From LLM is enabled after project documents are uploaded in Step A."}
        </p>
        <div className="ontology-property-body">
          <div className="ontology-property-row ontology-inline-field">
            <span className="ontology-property-row-label">Label Name:</span>
            <div className="ontology-property-row-editor">
              <input
                value={promptLabelEditor.labelName}
                readOnly={!promptLabelEditor.isNewLabel}
                onChange={(event) => onLabelNameChange(event.target.value)}
                placeholder={promptLabelEditor.isNewLabel ? "Enter new label name" : ""}
              />
            </div>
          </div>
          <div className="prompt-label-editor-tabs" role="tablist" aria-label="Prompt label editor tabs">
            {promptLabelEditorTabItems.map((tab) => {
              const isActive = activeTopPromptLabelEditorTab === tab.key;
              return (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  className={`prompt-label-editor-tab ${isActive ? "active" : ""}`}
                  onClick={() => onTabChange(tab.key)}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
          {isNodeEdgesTab && (
            <div className="prompt-label-editor-subtabs" role="tablist" aria-label="Node/Edges editor tabs">
              {nodeEdgesEditorTabItems.map((tab) => {
                const isActive = activeNodeEdgesEditorTab === tab.key;
                return (
                  <button
                    key={tab.key}
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    className={`prompt-label-editor-subtab ${isActive ? "active" : ""}`}
                    onClick={() => onNodeEdgesTabChange(tab.key)}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>
          )}

          {isPromptTemplateEditorTab ? (
            <div className="prompt-template-editor-wrap">
              {promptLabelEditor.loadingPromptTemplate && (
                <p className="field-note">Loading prompt template...</p>
              )}
              <div className="prompt-template-editor-head">
                <button
                  type="button"
                  className="prompt-template-preview-link"
                  onClick={() => {
                    const liveDraft = promptTemplateTextareaRef.current?.value;
                    if (typeof liveDraft === "string") {
                      onPromptTemplateDraftChange(activePromptLabelEditorTab, liveDraft);
                    }
                    onPromptTemplatePreviewToggle(activePromptLabelEditorTab);
                  }}
                  disabled={
                    promptLabelEditor.loadingPromptTemplate ||
                    promptLabelEditor.syncing ||
                    promptLabelEditor.savingTypes ||
                    Boolean(String(promptLabelEditor.updatingPromptTemplateKey ?? "").trim())
                  }
                >
                  {promptLabelEditor?.promptTemplatePreviewModes?.[activePromptLabelEditorTab]
                    ? "Back to Edit"
                    : "Preview Markdown"}
                </button>
                <button
                  type="button"
                  className="prompt-template-update-btn"
                  onClick={onUpdatePromptTemplate}
                  disabled={!canUpdatePromptTemplate}
                  title={
                    canUpdatePromptTemplate
                      ? "Save this prompt now"
                      : "No prompt changes to update"
                  }
                >
                  {isUpdatingPromptTemplate ? "Updating..." : "Update"}
                </button>
              </div>
              {promptLabelEditor?.promptTemplatePreviewModes?.[activePromptLabelEditorTab] ? (
                <div
                  className="prompt-template-preview"
                  style={{
                    minHeight: `${Math.max(
                      442,
                      Number(promptLabelEditor?.promptTemplateHeights?.[activePromptLabelEditorTab] ?? 442),
                    )}px`,
                  }}
                  dangerouslySetInnerHTML={{
                    __html: renderMarkdownToHtml(
                      String(promptLabelEditor.promptTemplateDrafts?.[activePromptLabelEditorTab] ?? ""),
                    ),
                  }}
                />
              ) : (
              <textarea
                ref={promptTemplateTextareaRef}
                className="prompt-template-editor-textarea"
                value={String(promptLabelEditor.promptTemplateDrafts?.[activePromptLabelEditorTab] ?? "")}
                style={{
                  height: `${Math.max(
                    442,
                    Number(promptLabelEditor?.promptTemplateHeights?.[activePromptLabelEditorTab] ?? 442),
                  )}px`,
                }}
                onChange={(event) =>
                  onPromptTemplateDraftChange(activePromptLabelEditorTab, event.target.value)
                }
                onMouseUp={(event) =>
                  onPromptTemplateHeightChange(activePromptLabelEditorTab, event.currentTarget.offsetHeight)
                }
                onTouchEnd={(event) =>
                  onPromptTemplateHeightChange(activePromptLabelEditorTab, event.currentTarget.offsetHeight)
                }
                disabled={
                  promptLabelEditor.loadingPromptTemplate ||
                  promptLabelEditor.syncing ||
                  promptLabelEditor.savingTypes ||
                  Boolean(String(promptLabelEditor.updatingPromptTemplateKey ?? "").trim())
                }
                spellCheck={false}
              />
              )}
            </div>
          ) : (
            <>
              {promptLabelEditor.loadingTypes && (
                <p className="field-note">Loading label types...</p>
              )}

              {PROMPT_LABEL_TYPE_ROWS.map((row) => {
                const disabled =
                  promptLabelEditor.syncing ||
                  promptLabelEditor.savingTypes ||
                  promptLabelEditor.generatingFromLlm ||
                  Boolean(String(promptLabelEditor.updatingPromptTemplateKey ?? "").trim());
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
                          onChange={(nextValues) => onTypeListChange(row.field, nextValues)}
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
                        onToggleTypeSectionCollapse(row.field);
                      }}
                      onKeyDown={(event) => {
                        if (disabled) return;
                        if (event.key !== "Enter" && event.key !== " ") return;
                        event.preventDefault();
                        onToggleTypeSectionCollapse(row.field);
                      }}
                      aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${row.label}`}
                      title={isCollapsed ? "Expand section" : "Collapse section"}
                    >
                      {isCollapsed ? "+" : "-"}
                    </span>
                  </div>
                );
              })}
            </>
          )}
        </div>
        {promptLabelEditor.notice && <p className="status-line">{promptLabelEditor.notice}</p>}
        {promptLabelEditor.error && <p className="ontology-editor-error">{promptLabelEditor.error}</p>}
        <div className="ontology-editor-actions prompt-label-editor-actions">
          {isNodeEdgesTab && (
            <div className="prompt-label-editor-actions-row prompt-label-editor-actions-row-top">
              <label className="prompt-label-keep-remain-toggle">
                <span className="prompt-label-keep-remain-text">Keep Remain</span>
                <span className="prompt-label-slider-switch">
                  <input
                    type="checkbox"
                    checked={Boolean(promptLabelEditor.keepRemainingOnGenerate)}
                    onChange={(event) => onKeepRemainingOnGenerateChange(event.target.checked)}
                    disabled={footerActionsDisabled}
                  />
                  <span className="prompt-label-slider-track" />
                </span>
              </label>
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={onGenerateFromLlm}
                disabled={disableGenerateFromLlm}
                title={generateFromLlmHelpText}
              >
                {promptLabelEditor.generatingFromLlm ? "Generating..." : "Generate From LLM"}
              </button>
            </div>
          )}
          <div className="prompt-label-editor-actions-row prompt-label-editor-actions-row-bottom">
            <button className="ontology-editor-cancel-btn" type="button" onClick={onClose} disabled={footerActionsDisabled}>
              Cancel
            </button>
            <button
              className="ontology-editor-cancel-btn"
              type="button"
              onClick={onRevertToDefault}
              disabled={promptLabelEditor.loadingTypes || footerActionsDisabled}
            >
              Revert to Default
            </button>
            <button
              className="ontology-editor-cancel-btn"
              type="button"
              onClick={onSyncFromDefault}
              disabled={(!isPromptTemplateTab(activePromptLabelEditorTab) && promptLabelEditor.isNewLabel) || footerActionsDisabled}
            >
              {promptLabelEditor.syncing ? "Syncing..." : "Sync From Default"}
            </button>
            <button
              className="action-btn"
              type="button"
              onClick={onSave}
              disabled={
                footerActionsDisabled ||
                (promptLabelEditor.isNewLabel && !isNodeEdgesContentTab) ||
                !String(promptLabelEditor.labelName ?? "").trim()
              }
            >
              {promptLabelEditor.savingTypes
                ? promptLabelEditor.isNewLabel
                  ? "Creating..."
                  : "Saving..."
                : promptLabelEditor.isNewLabel
                  ? isNodeEdgesContentTab
                    ? "Create Label"
                    : "Save Label"
                  : "Save Label"}
            </button>
          </div>
        </div>
      </article>
    </div>
  );
}
