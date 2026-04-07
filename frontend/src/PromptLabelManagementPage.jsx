import { useEffect, useRef, useState } from "react";

import TopBar from "./TopBar";
import EditableStringListEditor from "./components/EditableStringListEditor";
import { useTaskStore } from "./TaskStore/index";
import "./TaskPanel/prompt-label-editor.css";
import { renderMarkdownToHtml } from "./TaskPanel/markdownPreview";

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

const PROMPT_TEMPLATE_REQUIRED_VARIABLES = {
  ontology_output_extraction: ["combined_text"],
  entity_edge_generator_prompt: ["label_name", "combined_text"],
};

const validatePromptTemplateContent = (promptKey, content) => {
  const requiredVariables = Array.isArray(PROMPT_TEMPLATE_REQUIRED_VARIABLES?.[promptKey])
    ? PROMPT_TEMPLATE_REQUIRED_VARIABLES[promptKey]
    : [];
  if (requiredVariables.length === 0) {
    return { valid: true, missing: [] };
  }
  const body = String(content ?? "");
  const missing = requiredVariables.filter((variableName) => {
    const tokenPattern = new RegExp(`\\{\\{\\s*${variableName}\\s*\\}\\}`);
    return !tokenPattern.test(body);
  });
  return { valid: missing.length === 0, missing };
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

const PROMPT_TEMPLATE_TAB_FIELDS = [
  "ontology_prompt",
  "ontology_output_extraction",
  "entity_edge_generator_prompt",
];
const PROMPT_LABEL_EDITOR_TAB_ITEMS = [
  { key: "ontology_prompt", label: "ONTOLOGY Prompt" },
  { key: "ontology_output_extraction", label: "Ontology Output" },
  { key: "node_edges", label: "Node/Edges Extraction" },
];
const NODE_EDGES_EDITOR_TAB_ITEMS = [
  { key: "entity_edge_generator_prompt", label: "ENTITY_EDGE_GENERATOR Prompt" },
  { key: "node_edges_content", label: "Node/Edges Extraction" },
];

const createEmptyPromptTemplateDrafts = () => ({
  ontology_prompt: "",
  ontology_output_extraction: "",
  entity_edge_generator_prompt: "",
});

const createEmptyPromptTemplateTouchedState = () => ({
  ontology_prompt: false,
  ontology_output_extraction: false,
  entity_edge_generator_prompt: false,
});

const createEmptyPromptTemplateLoadedState = () => ({
  ontology_prompt: false,
  ontology_output_extraction: false,
  entity_edge_generator_prompt: false,
});

const createDefaultPromptTemplateHeights = () => ({
  ontology_prompt: 442,
  ontology_output_extraction: 442,
  entity_edge_generator_prompt: 442,
});

const createDefaultPromptTemplatePreviewModes = () => ({
  ontology_prompt: false,
  ontology_output_extraction: false,
  entity_edge_generator_prompt: false,
});

const isPromptTemplateTab = (tabKey) => PROMPT_TEMPLATE_TAB_FIELDS.includes(String(tabKey ?? "").trim());

export default function PromptLabelManagementPage({ onNavigate }) {
  const {
    state,
    fetchPromptLabels,
    createPromptLabel,
    deletePromptLabel,
    switchProject,
    generatePromptLabelTypeListsFromLlm,
    createDraftProject,
    getPromptLabelTypeLists,
    getPromptLabelPromptTemplate,
    updatePromptLabelPromptTemplate,
    syncPromptLabelPromptTemplateFromDefault,
    updatePromptLabelTypeLists,
  } = useTaskStore();
  const [pageError, setPageError] = useState("");
  const [pageNotice, setPageNotice] = useState("");
  const [deletingLabelName, setDeletingLabelName] = useState("");
  const [promptLabelEditor, setPromptLabelEditor] = useState({
    open: false,
    labelName: "",
    isNewLabel: false,
    activeTab: "ontology_prompt",
    nodeEdgesEditorTab: "entity_edge_generator_prompt",
    loadingTypes: false,
    loadingPromptTemplate: false,
    syncing: false,
    generatingFromLlm: false,
    updatingPromptTemplateKey: "",
    savingTypes: false,
    typesDraftTouched: false,
    typeLists: createEmptyPromptLabelTypeLists(),
    promptTemplateDrafts: createEmptyPromptTemplateDrafts(),
    promptTemplateDraftTouched: createEmptyPromptTemplateTouchedState(),
    promptTemplateDraftLoaded: createEmptyPromptTemplateLoadedState(),
    promptTemplateHeights: createDefaultPromptTemplateHeights(),
    promptTemplatePreviewModes: createDefaultPromptTemplatePreviewModes(),
    collapsedTypeSections: createPromptLabelTypeCollapseState(),
    notice: "",
    error: "",
  });
  const promptTemplateTextareaRef = useRef(null);
  const labels = state.promptLabelCatalog.items;
  const totalLabels = state.promptLabelCatalog.totalLabels ?? labels.length;
  const selectedProjectId = String(state.form?.projectId ?? "").trim();
  const hasUploadedProjectDocuments =
    Array.isArray(state.currentProject?.files) && state.currentProject.files.length > 0;
  const hasSelectedUploadFiles = Array.isArray(state.form?.files) && state.form.files.length > 0;
  const activeTopPromptLabelEditorTab = String(promptLabelEditor.activeTab ?? "ontology_prompt").trim();
  const activeNodeEdgesEditorTab = String(
    promptLabelEditor.nodeEdgesEditorTab ?? "entity_edge_generator_prompt",
  ).trim();
  const activePromptLabelEditorTab =
    activeTopPromptLabelEditorTab === "node_edges"
      ? activeNodeEdgesEditorTab
      : activeTopPromptLabelEditorTab;
  const canGenerateFromLlmWithProjectState = Boolean(selectedProjectId) || hasSelectedUploadFiles;
  const canGenerateFromLlm =
    activeTopPromptLabelEditorTab === "node_edges" && canGenerateFromLlmWithProjectState;
  const generateFromLlmHelpText =
    activeTopPromptLabelEditorTab !== "node_edges"
      ? "Generate From LLM is only available in Node/Edges Extraction tab."
      : hasUploadedProjectDocuments
        ? "Generate label lists from uploaded project documents."
        : selectedProjectId
          ? hasSelectedUploadFiles
            ? "Run Step A (Run Ontology Generate) first to upload the selected file(s)."
            : "Choose at least one file in Step A, then run Ontology Generate first."
          : hasSelectedUploadFiles
            ? "Will auto-create a draft project from selected files before generating."
            : "Select a project, or choose files so draft project can be created.";
  const hasPromptTemplateDraftChanges = Boolean(
    promptLabelEditor?.promptTemplateDraftTouched?.[activePromptLabelEditorTab],
  );
  const isUpdatingActivePromptTemplate =
    String(promptLabelEditor?.updatingPromptTemplateKey ?? "").trim() === activePromptLabelEditorTab;
  const canUpdateActivePromptTemplate =
    isPromptTemplateTab(activePromptLabelEditorTab) &&
    !promptLabelEditor.isNewLabel &&
    hasPromptTemplateDraftChanges &&
    !promptLabelEditor.loadingPromptTemplate &&
    !promptLabelEditor.syncing &&
    !promptLabelEditor.savingTypes &&
    !promptLabelEditor.generatingFromLlm &&
    !isUpdatingActivePromptTemplate &&
    Boolean(String(promptLabelEditor.labelName ?? "").trim());
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
      activeTab: "ontology_prompt",
      nodeEdgesEditorTab: "entity_edge_generator_prompt",
      loadingTypes: true,
      loadingPromptTemplate: false,
      syncing: false,
      generatingFromLlm: false,
      updatingPromptTemplateKey: "",
      savingTypes: false,
      typesDraftTouched: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      promptTemplateDrafts: createEmptyPromptTemplateDrafts(),
      promptTemplateDraftTouched: createEmptyPromptTemplateTouchedState(),
      promptTemplateDraftLoaded: createEmptyPromptTemplateLoadedState(),
      promptTemplateHeights: createDefaultPromptTemplateHeights(),
      promptTemplatePreviewModes: createDefaultPromptTemplatePreviewModes(),
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
      activeTab: "ontology_prompt",
      nodeEdgesEditorTab: "entity_edge_generator_prompt",
      loadingTypes: false,
      loadingPromptTemplate: false,
      syncing: false,
      generatingFromLlm: false,
      updatingPromptTemplateKey: "",
      savingTypes: false,
      typesDraftTouched: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      promptTemplateDrafts: createEmptyPromptTemplateDrafts(),
      promptTemplateDraftTouched: createEmptyPromptTemplateTouchedState(),
      promptTemplateDraftLoaded: createEmptyPromptTemplateLoadedState(),
      promptTemplateHeights: createDefaultPromptTemplateHeights(),
      promptTemplatePreviewModes: createDefaultPromptTemplatePreviewModes(),
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
      activeTab: "ontology_prompt",
      nodeEdgesEditorTab: "entity_edge_generator_prompt",
      loadingTypes: true,
      loadingPromptTemplate: false,
      syncing: false,
      generatingFromLlm: false,
      updatingPromptTemplateKey: "",
      savingTypes: false,
      typesDraftTouched: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      promptTemplateDrafts: createEmptyPromptTemplateDrafts(),
      promptTemplateDraftTouched: createEmptyPromptTemplateTouchedState(),
      promptTemplateDraftLoaded: createEmptyPromptTemplateLoadedState(),
      promptTemplateHeights: createDefaultPromptTemplateHeights(),
      promptTemplatePreviewModes: createDefaultPromptTemplatePreviewModes(),
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
    if (
      promptLabelEditor.loadingTypes ||
      promptLabelEditor.loadingPromptTemplate ||
      promptLabelEditor.syncing ||
      promptLabelEditor.generatingFromLlm ||
      promptLabelEditor.savingTypes ||
      Boolean(String(promptLabelEditor.updatingPromptTemplateKey ?? "").trim())
    ) {
      return;
    }
    setPromptLabelEditor({
      open: false,
      labelName: "",
      isNewLabel: false,
      activeTab: "ontology_prompt",
      nodeEdgesEditorTab: "entity_edge_generator_prompt",
      loadingTypes: false,
      loadingPromptTemplate: false,
      syncing: false,
      generatingFromLlm: false,
      updatingPromptTemplateKey: "",
      savingTypes: false,
      typesDraftTouched: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      promptTemplateDrafts: createEmptyPromptTemplateDrafts(),
      promptTemplateDraftTouched: createEmptyPromptTemplateTouchedState(),
      promptTemplateDraftLoaded: createEmptyPromptTemplateLoadedState(),
      promptTemplateHeights: createDefaultPromptTemplateHeights(),
      promptTemplatePreviewModes: createDefaultPromptTemplatePreviewModes(),
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

  const updatePromptTemplateDraft = (promptKey, nextValue) => {
    if (!isPromptTemplateTab(promptKey)) return;
    setPromptLabelEditor((current) => ({
      ...current,
      promptTemplateDrafts: {
        ...current.promptTemplateDrafts,
        [promptKey]: String(nextValue ?? ""),
      },
      promptTemplateDraftTouched: {
        ...createEmptyPromptTemplateTouchedState(),
        ...current.promptTemplateDraftTouched,
        [promptKey]: true,
      },
      promptTemplateDraftLoaded: {
        ...createEmptyPromptTemplateLoadedState(),
        ...current.promptTemplateDraftLoaded,
        [promptKey]: true,
      },
      notice: "",
      error: "",
    }));
  };

  const updatePromptTemplateHeight = (promptKey, nextHeight) => {
    if (!isPromptTemplateTab(promptKey)) return;
    const parsedHeight = Number(nextHeight);
    if (!Number.isFinite(parsedHeight)) return;
    const normalizedHeight = Math.max(442, Math.round(parsedHeight));
    setPromptLabelEditor((current) => ({
      ...current,
      promptTemplateHeights: {
        ...createDefaultPromptTemplateHeights(),
        ...current.promptTemplateHeights,
        [promptKey]: normalizedHeight,
      },
    }));
  };

  const togglePromptTemplatePreview = (promptKey) => {
    if (!isPromptTemplateTab(promptKey)) return;
    setPromptLabelEditor((current) => ({
      ...current,
      promptTemplatePreviewModes: {
        ...createDefaultPromptTemplatePreviewModes(),
        ...current.promptTemplatePreviewModes,
        [promptKey]: !Boolean(current?.promptTemplatePreviewModes?.[promptKey]),
      },
    }));
  };

  const setPromptLabelEditorTab = (tabKey) => {
    const normalizedTab = String(tabKey ?? "").trim();
    if (!normalizedTab) return;
    setPromptLabelEditor((current) => ({
      ...current,
      activeTab: normalizedTab,
      nodeEdgesEditorTab:
        normalizedTab === "node_edges"
          ? String(current?.nodeEdgesEditorTab ?? "entity_edge_generator_prompt").trim() ||
            "entity_edge_generator_prompt"
          : current.nodeEdgesEditorTab,
      loadingPromptTemplate: false,
      notice: "",
      error: "",
    }));
  };

  const updateActivePromptTemplate = async () => {
    const activeTopTab = String(promptLabelEditor.activeTab ?? "node_edges").trim();
    const activeNodeEdgesTab = String(
      promptLabelEditor.nodeEdgesEditorTab ?? "entity_edge_generator_prompt",
    ).trim();
    const activeTab = activeTopTab === "node_edges" ? activeNodeEdgesTab : activeTopTab;
    if (!isPromptTemplateTab(activeTab)) return;

    const labelName = String(promptLabelEditor.labelName ?? "").trim();
    if (!labelName) {
      setPromptLabelEditor((current) => ({
        ...current,
        error: "Label name is required.",
        notice: "",
      }));
      return;
    }
    if (promptLabelEditor.isNewLabel) {
      setPromptLabelEditor((current) => ({
        ...current,
        error: "Create label from Node/Edges Extraction content tab first.",
        notice: "",
      }));
      return;
    }
    if (!promptLabelEditor?.promptTemplateDraftTouched?.[activeTab]) {
      return;
    }

    const content = String(promptLabelEditor.promptTemplateDrafts?.[activeTab] ?? "");
    const validation = validatePromptTemplateContent(activeTab, content);
    if (!validation.valid) {
      setPromptLabelEditor((current) => ({
        ...current,
        error: `${activeTab.replace(/_/g, " ")} prompt must include: ${validation.missing.join(", ")}`,
        notice: "",
      }));
      return;
    }

    setPromptLabelEditor((current) => ({
      ...current,
      updatingPromptTemplateKey: activeTab,
      error: "",
      notice: "",
    }));
    try {
      await updatePromptLabelPromptTemplate(labelName, activeTab, content);
      await fetchPromptLabels({ syncFormLabel: false });
      setPromptLabelEditor((current) => ({
        ...current,
        updatingPromptTemplateKey: "",
        promptTemplateDraftTouched: {
          ...current.promptTemplateDraftTouched,
          [activeTab]: false,
        },
        promptTemplateDraftLoaded: {
          ...current.promptTemplateDraftLoaded,
          [activeTab]: true,
        },
        notice: "Prompt updated.",
        error: "",
      }));
    } catch (error) {
      setPromptLabelEditor((current) => ({
        ...current,
        updatingPromptTemplateKey: "",
        notice: "",
        error: String(error),
      }));
    }
  };

  const setNodeEdgesEditorTab = (tabKey) => {
    const normalizedTab = String(tabKey ?? "").trim();
    if (!normalizedTab) return;
    setPromptLabelEditor((current) => ({
      ...current,
      nodeEdgesEditorTab: normalizedTab,
      loadingPromptTemplate: false,
      notice: "",
      error: "",
    }));
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
    const activeTopTab = String(promptLabelEditor.activeTab ?? "node_edges").trim();
    const activeNodeEdgesTab = String(
      promptLabelEditor.nodeEdgesEditorTab ?? "entity_edge_generator_prompt",
    ).trim();
    const activeTab = activeTopTab === "node_edges" ? activeNodeEdgesTab : activeTopTab;
    const isPromptTab = isPromptTemplateTab(activeTab);
    const existingLabels = new Set(labels.map((item) => String(item?.name ?? "").trim().toLowerCase()).filter(Boolean));
    if (promptLabelEditor.isNewLabel && existingLabels.has(labelName.toLowerCase())) {
      setPromptLabelEditor((current) => ({
        ...current,
        error: `Category label '${labelName}' already exists. Choose another name.`,
        notice: "",
      }));
      return;
    }
    if (promptLabelEditor.isNewLabel && activeTab !== "node_edges_content") {
      setPromptLabelEditor((current) => ({
        ...current,
        error: "Create label from Node/Edges Extraction content tab first.",
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
        for (const templateKey of PROMPT_TEMPLATE_TAB_FIELDS) {
          const hasDraft = Boolean(
            promptLabelEditor?.promptTemplateDraftLoaded?.[templateKey] ||
            promptLabelEditor?.promptTemplateDraftTouched?.[templateKey],
          );
          const content = hasDraft
            ? String(promptLabelEditor.promptTemplateDrafts?.[templateKey] ?? "")
            : String((await getPromptLabelPromptTemplate("Production", templateKey))?.content ?? "");
          const validation = validatePromptTemplateContent(templateKey, content);
          if (!validation.valid) {
            throw new Error(
              `${templateKey.replace(/_/g, " ")} prompt must include: ${validation.missing.join(", ")}`,
            );
          }
          await updatePromptLabelPromptTemplate(labelName, templateKey, content);
        }
      }

      if (isPromptTab) {
        const content = String(promptLabelEditor.promptTemplateDrafts?.[activeTab] ?? "");
        const validation = validatePromptTemplateContent(activeTab, content);
        if (!validation.valid) {
          throw new Error(
            `${activeTab.replace(/_/g, " ")} prompt must include: ${validation.missing.join(", ")}`,
          );
        }
        await updatePromptLabelPromptTemplate(labelName, activeTab, content);
      } else {
        const payload = normalizePromptLabelTypeListsPayload(promptLabelEditor.typeLists);
        await updatePromptLabelTypeLists(labelName, payload);
      }

      await fetchPromptLabels({ syncFormLabel: false });
      setPromptLabelEditor({
        open: false,
        labelName: "",
        isNewLabel: false,
        activeTab: "ontology_prompt",
        nodeEdgesEditorTab: "entity_edge_generator_prompt",
        loadingTypes: false,
        loadingPromptTemplate: false,
        syncing: false,
        generatingFromLlm: false,
        updatingPromptTemplateKey: "",
        savingTypes: false,
        typesDraftTouched: false,
        typeLists: createEmptyPromptLabelTypeLists(),
        promptTemplateDrafts: createEmptyPromptTemplateDrafts(),
        promptTemplateDraftTouched: createEmptyPromptTemplateTouchedState(),
        promptTemplateDraftLoaded: createEmptyPromptTemplateLoadedState(),
        promptTemplateHeights: createDefaultPromptTemplateHeights(),
        promptTemplatePreviewModes: createDefaultPromptTemplatePreviewModes(),
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
    if (
      promptLabelEditor.loadingTypes ||
      promptLabelEditor.loadingPromptTemplate ||
      promptLabelEditor.syncing ||
      promptLabelEditor.generatingFromLlm ||
      promptLabelEditor.savingTypes
    ) {
      return;
    }
    const activeTopTab = String(promptLabelEditor.activeTab ?? "node_edges").trim();
    const activeNodeEdgesTab = String(
      promptLabelEditor.nodeEdgesEditorTab ?? "entity_edge_generator_prompt",
    ).trim();
    const activeTab = activeTopTab === "node_edges" ? activeNodeEdgesTab : activeTopTab;
    const isPromptTab = isPromptTemplateTab(activeTab);
    setPromptLabelEditor((current) => ({
      ...current,
      loadingTypes: !isPromptTab,
      loadingPromptTemplate: isPromptTab,
      notice: "",
      error: "",
    }));
    try {
      if (isPromptTab) {
        const result = await getPromptLabelPromptTemplate("Production", activeTab);
        setPromptLabelEditor((current) => ({
          ...current,
          loadingTypes: false,
          loadingPromptTemplate: false,
          promptTemplateDrafts: {
            ...current.promptTemplateDrafts,
            [activeTab]: String(result?.content ?? ""),
          },
          promptTemplateDraftTouched: {
            ...current.promptTemplateDraftTouched,
            [activeTab]: false,
          },
          promptTemplateDraftLoaded: {
            ...current.promptTemplateDraftLoaded,
            [activeTab]: true,
          },
          notice: "Reverted current tab to Production defaults. Save to apply changes.",
          error: "",
        }));
        return;
      }

      const result = await getPromptLabelTypeLists("Production");
      setPromptLabelEditor((current) => ({
        ...current,
        loadingTypes: false,
        loadingPromptTemplate: false,
        typesDraftTouched: false,
        typeLists: normalizePromptLabelTypeListsPayload(result?.types),
        notice: "Reverted Node/Edges Extraction content to Production defaults. Save to apply changes.",
        error: "",
      }));
    } catch (error) {
      setPromptLabelEditor((current) => ({
        ...current,
        loadingTypes: false,
        loadingPromptTemplate: false,
        notice: "",
        error: String(error),
      }));
    }
  };

  const syncPromptLabelContent = async () => {
    if (
      promptLabelEditor.loadingTypes ||
      promptLabelEditor.loadingPromptTemplate ||
      promptLabelEditor.syncing ||
      promptLabelEditor.generatingFromLlm ||
      promptLabelEditor.savingTypes
    ) {
      return;
    }
    const activeTopTab = String(promptLabelEditor.activeTab ?? "node_edges").trim();
    const activeNodeEdgesTab = String(
      promptLabelEditor.nodeEdgesEditorTab ?? "entity_edge_generator_prompt",
    ).trim();
    const activeTab = activeTopTab === "node_edges" ? activeNodeEdgesTab : activeTopTab;
    const isPromptTab = isPromptTemplateTab(activeTab);

    setPromptLabelEditor((current) => ({
      ...current,
      syncing: true,
      loadingTypes: !isPromptTab,
      loadingPromptTemplate: isPromptTab,
      notice: "",
      error: "",
    }));
    try {
      if (isPromptTab) {
        if (promptLabelEditor.isNewLabel) {
          const result = await getPromptLabelPromptTemplate("Production", activeTab);
          setPromptLabelEditor((current) => ({
            ...current,
            syncing: false,
            loadingPromptTemplate: false,
            promptTemplateDrafts: {
              ...current.promptTemplateDrafts,
              [activeTab]: String(result?.content ?? ""),
            },
            promptTemplateDraftTouched: {
              ...current.promptTemplateDraftTouched,
              [activeTab]: false,
            },
            promptTemplateDraftLoaded: {
              ...current.promptTemplateDraftLoaded,
              [activeTab]: true,
            },
            notice: "Loaded Production default for current tab. Save to apply changes.",
            error: "",
          }));
          return;
        }

        const labelName = String(promptLabelEditor.labelName ?? "").trim();
        if (!labelName) {
          throw new Error("Label name is required.");
        }
        const result = await syncPromptLabelPromptTemplateFromDefault(labelName, activeTab);
        await fetchPromptLabels({ syncFormLabel: false });
        setPromptLabelEditor((current) => ({
          ...current,
          syncing: false,
          loadingPromptTemplate: false,
          promptTemplateDrafts: {
            ...current.promptTemplateDrafts,
            [activeTab]: String(result?.content ?? ""),
          },
          promptTemplateDraftTouched: {
            ...current.promptTemplateDraftTouched,
            [activeTab]: false,
          },
          promptTemplateDraftLoaded: {
            ...current.promptTemplateDraftLoaded,
            [activeTab]: true,
          },
          notice: "Synced current tab from Production defaults.",
          error: "",
        }));
        return;
      }

      const result = await getPromptLabelTypeLists("Production");
      setPromptLabelEditor((current) => ({
        ...current,
        syncing: false,
        loadingTypes: false,
        loadingPromptTemplate: false,
        typesDraftTouched: false,
        typeLists: normalizePromptLabelTypeListsPayload(result?.types),
        notice: "Synced Node/Edges Extraction content from Production defaults. Save to apply changes.",
        error: "",
      }));
    } catch (error) {
      setPromptLabelEditor((current) => ({
        ...current,
        syncing: false,
        loadingTypes: false,
        loadingPromptTemplate: false,
        notice: "",
        error: String(error),
      }));
    }
  };

  const generateNewPromptLabelFromLlm = async () => {
    if (!promptLabelEditor.isNewLabel) return;
    if (String(promptLabelEditor.activeTab ?? "").trim() !== "node_edges") {
      setPromptLabelEditor((current) => ({
        ...current,
        notice: "",
        error: "Generate From LLM is only available in Node/Edges Extraction tab.",
      }));
      return;
    }
    if (
      promptLabelEditor.loadingTypes ||
      promptLabelEditor.loadingPromptTemplate ||
      promptLabelEditor.syncing ||
      promptLabelEditor.generatingFromLlm ||
      promptLabelEditor.savingTypes
    ) {
      return;
    }
    const labelName = String(promptLabelEditor.labelName ?? "").trim();
    if (!labelName) {
      setPromptLabelEditor((current) => ({
        ...current,
        notice: "",
        error: "Label name is required.",
      }));
      return;
    }
    let resolvedProjectId = selectedProjectId;
    const isExistingProject = Boolean(resolvedProjectId);
    if (!resolvedProjectId && !hasSelectedUploadFiles) {
      setPromptLabelEditor((current) => ({
        ...current,
        notice: "",
        error: "Select a project or choose files first so a draft project can be created.",
      }));
      return;
    }
    if (isExistingProject && !hasUploadedProjectDocuments) {
      setPromptLabelEditor((current) => ({
        ...current,
        notice: "",
        error: hasSelectedUploadFiles
          ? "Run Step A first to upload the selected file(s), then try Generate From LLM again."
          : "Choose at least one file in Step A, run Ontology Generate, then try Generate From LLM.",
      }));
      return;
    }

    setPromptLabelEditor((current) => ({
      ...current,
      generatingFromLlm: true,
      notice: "",
      error: "",
    }));
    try {
      const entityEdgeGeneratorPromptOverride = promptLabelEditor?.promptTemplateDraftTouched
        ?.entity_edge_generator_prompt
        ? String(promptLabelEditor?.promptTemplateDrafts?.entity_edge_generator_prompt ?? "")
        : undefined;

      if (!resolvedProjectId) {
        setPromptLabelEditor((current) => ({
          ...current,
          notice: "Preparing draft project from selected files...",
          error: "",
        }));
        const draftProject = await createDraftProject({
          projectName: state.form?.projectName,
          promptLabel: state.form?.promptLabel,
          graphBackend: state.form?.graphBackend,
          files: state.form?.files,
        });
        const draftProjectId = String(draftProject?.project_id ?? "").trim();
        if (!draftProjectId) {
          throw new Error("Draft project id is missing");
        }
        resolvedProjectId = draftProjectId;
        await switchProject(draftProjectId, draftProject?.project_workspace_id ?? "");
      }

      const generatedResult = await generatePromptLabelTypeListsFromLlm(labelName, {
        projectId: resolvedProjectId,
        entityEdgeGeneratorPromptContent: entityEdgeGeneratorPromptOverride,
      });
      const processedDocuments = Number(generatedResult?.processed_documents ?? 0);
      setPromptLabelEditor((current) => ({
        ...current,
        generatingFromLlm: false,
        typesDraftTouched: false,
        typeLists: normalizePromptLabelTypeListsPayload(generatedResult?.types),
        notice: `Generated from LLM using ${processedDocuments} document${processedDocuments === 1 ? "" : "s"}. Review and save.`,
        error: "",
      }));
    } catch (error) {
      setPromptLabelEditor((current) => ({
        ...current,
        generatingFromLlm: false,
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

  useEffect(() => {
    if (!promptLabelEditor.open) return undefined;
    const activeTopTab = String(promptLabelEditor.activeTab ?? "").trim();
    const activeNodeEdgesTab = String(
      promptLabelEditor.nodeEdgesEditorTab ?? "entity_edge_generator_prompt",
    ).trim();
    const activeTab = activeTopTab === "node_edges" ? activeNodeEdgesTab : activeTopTab;
    if (!isPromptTemplateTab(activeTab)) return undefined;
    if (promptLabelEditor?.promptTemplateDraftLoaded?.[activeTab]) return undefined;

    const normalizedLabelName = String(promptLabelEditor.labelName ?? "").trim();
    const requestLabelName =
      promptLabelEditor.isNewLabel || !normalizedLabelName ? "Production" : normalizedLabelName;

    let cancelled = false;
    setPromptLabelEditor((current) => ({
      ...current,
      loadingPromptTemplate: true,
      error: "",
    }));

    getPromptLabelPromptTemplate(requestLabelName, activeTab)
      .then((result) => {
        if (cancelled) return;
        setPromptLabelEditor((current) => {
          const currentTopTab = String(current.activeTab ?? "").trim();
          const currentNodeEdgesTab = String(
            current.nodeEdgesEditorTab ?? "entity_edge_generator_prompt",
          ).trim();
          const currentActiveTab =
            currentTopTab === "node_edges" ? currentNodeEdgesTab : currentTopTab;
          if (!current.open || currentActiveTab !== activeTab) return current;
          const isTouched = Boolean(current?.promptTemplateDraftTouched?.[activeTab]);
          return {
            ...current,
            loadingPromptTemplate: false,
            promptTemplateDraftLoaded: {
              ...current.promptTemplateDraftLoaded,
              [activeTab]: true,
            },
            promptTemplateDrafts: isTouched
              ? current.promptTemplateDrafts
              : {
                ...current.promptTemplateDrafts,
                [activeTab]: String(result?.content ?? ""),
              },
          };
        });
      })
      .catch((error) => {
        if (cancelled) return;
        setPromptLabelEditor((current) => ({
          ...current,
          loadingPromptTemplate: false,
          error: String(error),
        }));
      });

    return () => {
      cancelled = true;
    };
  }, [
    promptLabelEditor.open,
    promptLabelEditor.activeTab,
    promptLabelEditor.nodeEdgesEditorTab,
    promptLabelEditor.isNewLabel ? "__new_label__" : promptLabelEditor.labelName,
    promptLabelEditor.isNewLabel,
  ]);

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
                onClick={closePromptLabelEditor}
                disabled={
                  promptLabelEditor.loadingTypes ||
                  promptLabelEditor.loadingPromptTemplate ||
                  promptLabelEditor.syncing ||
                  promptLabelEditor.generatingFromLlm ||
                  promptLabelEditor.savingTypes
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
                    ? "Create a new label from empty values, clone values, sync from Production defaults, or generate from uploaded docs."
                    : "Edit Node/Edges extraction lists for this label. Use Revert to Default to load Production values."}
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
              <div className="prompt-label-editor-tabs" role="tablist" aria-label="Prompt label editor tabs">
                {PROMPT_LABEL_EDITOR_TAB_ITEMS.map((tab) => {
                  const isActive = activeTopPromptLabelEditorTab === tab.key;
                  return (
                    <button
                      key={tab.key}
                      type="button"
                      role="tab"
                      aria-selected={isActive}
                      className={`prompt-label-editor-tab ${isActive ? "active" : ""}`}
                      onClick={() => setPromptLabelEditorTab(tab.key)}
                    >
                      {tab.label}
                    </button>
                  );
                })}
              </div>
              {activeTopPromptLabelEditorTab === "node_edges" && (
                <div className="prompt-label-editor-subtabs" role="tablist" aria-label="Node/Edges editor tabs">
                  {NODE_EDGES_EDITOR_TAB_ITEMS.map((tab) => {
                    const isActive = activeNodeEdgesEditorTab === tab.key;
                    return (
                      <button
                        key={tab.key}
                        type="button"
                        role="tab"
                        aria-selected={isActive}
                        className={`prompt-label-editor-subtab ${isActive ? "active" : ""}`}
                        onClick={() => setNodeEdgesEditorTab(tab.key)}
                      >
                        {tab.label}
                      </button>
                    );
                  })}
                </div>
              )}

              {isPromptTemplateTab(activePromptLabelEditorTab) ? (
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
                          updatePromptTemplateDraft(activePromptLabelEditorTab, liveDraft);
                        }
                        togglePromptTemplatePreview(activePromptLabelEditorTab);
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
                      onClick={updateActivePromptTemplate}
                      disabled={!canUpdateActivePromptTemplate}
                      title={
                        canUpdateActivePromptTemplate
                          ? "Save this prompt now"
                          : "No prompt changes to update"
                      }
                    >
                      {isUpdatingActivePromptTemplate ? "Updating..." : "Update"}
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
                        updatePromptTemplateDraft(activePromptLabelEditorTab, event.target.value)
                      }
                      onMouseUp={(event) =>
                        updatePromptTemplateHeight(activePromptLabelEditorTab, event.currentTarget.offsetHeight)
                      }
                      onTouchEnd={(event) =>
                        updatePromptTemplateHeight(activePromptLabelEditorTab, event.currentTarget.offsetHeight)
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
                    const disabled =
                      promptLabelEditor.syncing ||
                      promptLabelEditor.generatingFromLlm ||
                      promptLabelEditor.savingTypes ||
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
                </>
              )}
            </div>
            {promptLabelEditor.notice && <p className="status-line">{promptLabelEditor.notice}</p>}
            {promptLabelEditor.error && <p className="ontology-editor-error">{promptLabelEditor.error}</p>}
            <div className="ontology-editor-actions">
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={closePromptLabelEditor}
                disabled={
                  promptLabelEditor.loadingTypes ||
                  promptLabelEditor.loadingPromptTemplate ||
                  promptLabelEditor.syncing ||
                  promptLabelEditor.generatingFromLlm ||
                  promptLabelEditor.savingTypes ||
                  Boolean(String(promptLabelEditor.updatingPromptTemplateKey ?? "").trim())
                }
              >
                Cancel
              </button>
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={syncPromptLabelContent}
                disabled={
                  promptLabelEditor.loadingTypes ||
                  promptLabelEditor.loadingPromptTemplate ||
                  promptLabelEditor.syncing ||
                  promptLabelEditor.generatingFromLlm ||
                  promptLabelEditor.savingTypes ||
                  Boolean(String(promptLabelEditor.updatingPromptTemplateKey ?? "").trim())
                }
              >
                {promptLabelEditor.syncing ? "Syncing..." : "Sync From Default"}
              </button>
              {promptLabelEditor.isNewLabel && activeTopPromptLabelEditorTab === "node_edges" && (
                <button
                  className="ontology-editor-cancel-btn"
                  type="button"
                  onClick={generateNewPromptLabelFromLlm}
                  disabled={
                    promptLabelEditor.loadingTypes ||
                    promptLabelEditor.loadingPromptTemplate ||
                    promptLabelEditor.syncing ||
                    promptLabelEditor.generatingFromLlm ||
                    promptLabelEditor.savingTypes ||
                    Boolean(String(promptLabelEditor.updatingPromptTemplateKey ?? "").trim()) ||
                    !canGenerateFromLlm
                  }
                  title={generateFromLlmHelpText}
                >
                  {promptLabelEditor.generatingFromLlm ? "Generating..." : "Generate From LLM"}
                </button>
              )}
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={revertPromptLabelEditorToDefault}
                disabled={
                  promptLabelEditor.loadingTypes ||
                  promptLabelEditor.loadingPromptTemplate ||
                  promptLabelEditor.syncing ||
                  promptLabelEditor.generatingFromLlm ||
                  promptLabelEditor.savingTypes ||
                  Boolean(String(promptLabelEditor.updatingPromptTemplateKey ?? "").trim())
                }
              >
                Revert to Default
              </button>
              <button
                className="action-btn"
                type="button"
                onClick={savePromptLabelTypeLists}
                disabled={
                  promptLabelEditor.syncing ||
                  promptLabelEditor.loadingPromptTemplate ||
                  promptLabelEditor.generatingFromLlm ||
                  promptLabelEditor.savingTypes ||
                  Boolean(String(promptLabelEditor.updatingPromptTemplateKey ?? "").trim()) ||
                  (promptLabelEditor.isNewLabel && activePromptLabelEditorTab !== "node_edges_content") ||
                  !String(promptLabelEditor.labelName ?? "").trim()
                }
              >
                {promptLabelEditor.savingTypes
                  ? promptLabelEditor.isNewLabel
                    ? "Creating..."
                    : "Saving..."
                  : promptLabelEditor.isNewLabel
                    ? "Create Label"
                    : "Save Label"}
              </button>
            </div>
          </article>
        </div>
      )}
    </div>
  );
}
