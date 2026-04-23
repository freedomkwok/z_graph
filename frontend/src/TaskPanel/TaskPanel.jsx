import { useEffect, useRef, useState } from "react";

import EditableStringListEditor from "../components/EditableStringListEditor";
import JsonListEditor from "../components/JsonListEditor";
import TypeTagEditor from "../components/TypeTagEditor";
import PromptLabelEditorModal from "./components/PromptLabelEditorModal";
import { useTaskStore } from "../TaskStore/index";
import {
  PROMPT_LABEL_FIELD_PAIR_MAP,
  PROMPT_LABEL_TYPE_FIELDS,
  buildAbsoluteApiUrl,
  clonePlainData,
  createEmptyPromptLabelTypeLists,
  createPromptLabelTypeCollapseState,
  extractOntologyTypeDrafts,
  findTypeDefinitionByName,
  hasTypeDefinitionChanged,
  mergeTypeDefinition,
  mergePromptLabelTypeLists,
  normalizePromptLabelTypeListValues,
  normalizePromptLabelTypeListsPayload,
  normalizeStringList,
  normalizeTypeKey,
  normalizeTypeTag,
  remapTypeDefinitions,
  removeCrossListDuplicates,
  sanitizeEntityTypeDraft,
  sanitizeRelationshipTypeDraft,
  validatePromptTemplateContent,
} from "./utils";
import "./prompt-label-editor.css";

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

const areTypeDefinitionListsEquivalent = (baseDefinitions, nextDefinitions, mode) => {
  const baseList = Array.isArray(baseDefinitions) ? baseDefinitions : [];
  const nextList = Array.isArray(nextDefinitions) ? nextDefinitions : [];
  if (baseList.length !== nextList.length) return false;
  for (const base of baseList) {
    const baseName = normalizeTypeTag(base?.name);
    if (!baseName) return false;
    const next = findTypeDefinitionByName(nextList, baseName);
    if (!next) return false;
    if (hasTypeDefinitionChanged(base, next, mode)) return false;
  }
  return true;
};

export default function TaskPanel() {
  const {
    state,
    setViewMode,
    setFormField,
    setProjectPromptLabel,
    switchProject,
    createPromptLabel,
    fetchPromptLabels,
    generatePromptLabelTypeListsFromLlm,
    createDraftProject,
    getPromptLabelTypeLists,
    getPromptLabelPromptTemplate,
    updatePromptLabelPromptTemplate,
    syncPromptLabelPromptTemplateFromDefault,
    updatePromptLabelTypeLists,
    setFiles,
    runOntologyGenerate,
    cancelOntologyTask,
    runGraphBuild,
    cancelGraphBuild,
    updateProjectRefreshDataWhileBuild,
    updateProjectOntologyTypes,
    fetchProjectOntologyVersions,
    addSystemLog,
  } =
    useTaskStore();
  const {
    form,
    ontologyTask,
    graphTask,
    graphResumeCandidate,
    systemLogs,
    promptLabelCatalog,
    viewMode,
    currentProject,
    backendHealth,
  } =
    state;
  const logContainerRef = useRef(null);
  const promptLabelDropdownRef = useRef(null);
  const [activeStepTab, setActiveStepTab] = useState("A");
  const [activeBackendTab, setActiveBackendTab] = useState("build");
  const [ontologyEditorOpen, setOntologyEditorOpen] = useState(false);
  const [ontologyEditorTab, setOntologyEditorTab] = useState("entity");
  const [ontologyEditorRemoveMode, setOntologyEditorRemoveMode] = useState({
    entity: false,
    relationship: false,
  });
  const [ontologyVersions, setOntologyVersions] = useState([]);
  const [originalEntityTypes, setOriginalEntityTypes] = useState([]);
  const [originalEdgeTypes, setOriginalEdgeTypes] = useState([]);
  const [ontologyMergeSelection, setOntologyMergeSelection] = useState({
    entity: [],
    relationship: [],
  });
  const [ontologyGeneratedDiff, setOntologyGeneratedDiff] = useState({
    entity: false,
    relationship: false,
  });
  const [ontologyMergeRequired, setOntologyMergeRequired] = useState(false);
  const [draftEntityTypes, setDraftEntityTypes] = useState([]);
  const [draftEdgeTypes, setDraftEdgeTypes] = useState([]);
  const [typePropertyEditor, setTypePropertyEditor] = useState({
    open: false,
    mode: "",
    sourceList: "draft",
    index: -1,
    draft: null,
    jsonTexts: {},
    invalidJsonIndexes: {},
    error: "",
  });
  const [savingOntologyTypes, setSavingOntologyTypes] = useState(false);
  const [ontologyEditorError, setOntologyEditorError] = useState("");
  const [promptLabelEditor, setPromptLabelEditor] = useState({
    open: false,
    labelName: "",
    isNewLabel: false,
    activeTab: "ontology_prompt",
    nodeEdgesEditorTab: "entity_edge_generator_prompt",
    loadingTypes: false,
    loadingPromptTemplate: false,
    savingTypes: false,
    typesDraftTouched: false,
    typeLists: createEmptyPromptLabelTypeLists(),
    promptTemplateDrafts: createEmptyPromptTemplateDrafts(),
    promptTemplateDraftTouched: createEmptyPromptTemplateTouchedState(),
    promptTemplateDraftLoaded: createEmptyPromptTemplateLoadedState(),
    promptTemplateHeights: createDefaultPromptTemplateHeights(),
    promptTemplatePreviewModes: createDefaultPromptTemplatePreviewModes(),
    collapsedTypeSections: createPromptLabelTypeCollapseState(),
    keepRemainingOnGenerate: false,
    syncing: false,
    generatingFromLlm: false,
    updatingPromptTemplateKey: "",
    notice: "",
    error: "",
  });
  const [promptLabelDropdownOpen, setPromptLabelDropdownOpen] = useState(false);
  const [copiedEndpointPath, setCopiedEndpointPath] = useState("");
  const [showRuntimeControls, setShowRuntimeControls] = useState(true);
  const copyEndpointToastTimerRef = useRef(null);
  const [ontologyElapsedNowMs, setOntologyElapsedNowMs] = useState(() => Date.now());
  const [graphElapsedNowMs, setGraphElapsedNowMs] = useState(() => Date.now());

  const stepBUnlocked =
    ontologyTask.status === "success" || graphTask.status === "running" || graphTask.status === "success";
  const isOntologyTaskRunning = ontologyTask.status === "running";
  const hasOntologyTaskId = Boolean(String(ontologyTask.taskId ?? "").trim());
  const isGraphTaskRunning =
    graphTask.status === "running" && Boolean(String(graphTask.taskId ?? "").trim());
  const isAnyTaskRunning = isOntologyTaskRunning || isGraphTaskRunning;
  const normalizedCurrentProjectId = String(form.projectId ?? "").trim();
  const hydratedCurrentProjectId = String(currentProject?.project_id ?? "").trim();
  const hasHydratedCurrentProject =
    Boolean(normalizedCurrentProjectId) && hydratedCurrentProjectId === normalizedCurrentProjectId;
  const isProjectCreated = hasHydratedCurrentProject;
  const canOpenOntologyEditor = Boolean(form.projectId) && ontologyTask.status !== "running";
  const isEntityTab = ontologyEditorTab === "entity";
  const draftEntityTypeNames = draftEntityTypes.map((item) => normalizeTypeTag(item?.name)).filter(Boolean);
  const draftEdgeTypeNames = draftEdgeTypes.map((item) => normalizeTypeTag(item?.name)).filter(Boolean);
  const originalEntityTypeNames = originalEntityTypes
    .map((item) => normalizeTypeTag(item?.name))
    .filter(Boolean);
  const originalEdgeTypeNames = originalEdgeTypes.map((item) => normalizeTypeTag(item?.name)).filter(Boolean);
  const changedEntityTypeNames = originalEntityTypeNames.filter((name) =>
    hasTypeDefinitionChanged(
      findTypeDefinitionByName(originalEntityTypes, name),
      findTypeDefinitionByName(draftEntityTypes, name),
      "entity",
    ),
  );
  const changedEdgeTypeNames = originalEdgeTypeNames.filter((name) =>
    hasTypeDefinitionChanged(
      findTypeDefinitionByName(originalEdgeTypes, name),
      findTypeDefinitionByName(draftEdgeTypes, name),
      "relationship",
    ),
  );
  const isTypePropertyEditorOpen = Boolean(typePropertyEditor.open);
  const hasOntologyGeneratedDiff = ontologyGeneratedDiff.entity || ontologyGeneratedDiff.relationship;
  const canRunGraphBuild = graphTask.status !== "running" && stepBUnlocked && !ontologyMergeRequired;
  const resumeTotalBatches = Number(graphResumeCandidate?.totalBatches);
  const resumeLastCompletedBatchIndex = Number(graphResumeCandidate?.lastCompletedBatchIndex);
  const canShowResumeGraphBuild =
    canRunGraphBuild &&
    !isGraphTaskRunning &&
    graphResumeCandidate &&
    Number.isFinite(resumeTotalBatches) &&
    resumeTotalBatches > 0 &&
    Number.isFinite(resumeLastCompletedBatchIndex);
  const resumeNextBatch = canShowResumeGraphBuild
    ? Math.min(Math.max(resumeLastCompletedBatchIndex + 2, 1), resumeTotalBatches)
    : 1;
  const canConfirmOntologyEditor = !savingOntologyTypes && !isTypePropertyEditorOpen && !ontologyMergeRequired;
  const rawPromptLabelItems =
    promptLabelCatalog.items.length > 0
      ? promptLabelCatalog.items
      : [{ name: form.promptLabel || "Production", display_name: form.promptLabel || "Production" }];
  const projectScopedDisplayNames = new Set(
    rawPromptLabelItems
      .filter((item) => {
        const itemProjectId = String(item?.project_id ?? "").trim();
        return (
          Boolean(itemProjectId) &&
          Boolean(normalizedCurrentProjectId) &&
          itemProjectId.toLowerCase() === normalizedCurrentProjectId.toLowerCase()
        );
      })
      .map((item) => String(item?.display_name ?? item?.name ?? "").trim().toLowerCase())
      .filter(Boolean),
  );
  const promptLabelItems = rawPromptLabelItems.filter((item) => {
    const itemProjectId = String(item?.project_id ?? "").trim();
    if (itemProjectId) {
      return (
        Boolean(normalizedCurrentProjectId) &&
        itemProjectId.toLowerCase() === normalizedCurrentProjectId.toLowerCase()
      );
    }
    const displayName = String(item?.display_name ?? item?.name ?? "").trim().toLowerCase();
    if (!displayName) return false;
    return !projectScopedDisplayNames.has(displayName);
  });
  const hasCurrentProjectLabelAssociation = Boolean(currentProject?.prompt_label_info?.is_project_scoped);
  const hasSelectedProject = Boolean(normalizedCurrentProjectId);
  const isZepCloudBackend = String(backendHealth?.zepBackend ?? "")
    .trim()
    .toLowerCase() === "zep_cloud";
  const hasUploadedProjectDocuments =
    Array.isArray(currentProject?.files) && currentProject.files.length > 0;
  const hasSelectedUploadFiles = Array.isArray(form.files) && form.files.length > 0;
  const ontologyStartedAtMs = Date.parse(String(ontologyTask.startedAt ?? ""));
  const hasOntologyStartedAtMs = Number.isFinite(ontologyStartedAtMs);
  const ontologyRunSeconds =
    ontologyTask.status === "running" && hasOntologyStartedAtMs
      ? Math.max(0, Math.floor((ontologyElapsedNowMs - ontologyStartedAtMs) / 1000))
      : 0;
  const taskPollIntervalMs = Math.max(500, Number(backendHealth?.taskPollIntervalMs ?? 2000) || 2000);
  const taskPollIntervalSeconds = (taskPollIntervalMs / 1000).toFixed(
    Number.isInteger(taskPollIntervalMs / 1000) ? 0 : 1,
  );
  const refreshDataPollSecondsValue = Number(form.refreshDataPollSeconds);
  const refreshDataPollSeconds =
    Number.isFinite(refreshDataPollSecondsValue) && refreshDataPollSecondsValue > 0
      ? Math.floor(refreshDataPollSecondsValue)
      : 20;
  const graphPollIntervalSeconds = refreshDataPollSeconds;
  const graphStartedAtMs = Date.parse(String(graphTask.startedAt ?? ""));
  const hasGraphStartedAtMs = Number.isFinite(graphStartedAtMs);
  const graphRunSeconds =
    graphTask.status === "running" && hasGraphStartedAtMs
      ? Math.max(0, Math.floor((graphElapsedNowMs - graphStartedAtMs) / 1000))
      : 0;
  const normalizedChunkMode = String(form.chunkMode ?? "").trim().toLowerCase();
  const isLlmOnlyChunkMode =
    normalizedChunkMode === "semantic" || normalizedChunkMode === "llama_index";
  const rawGraphitiEmbeddingModelOptions = Array.isArray(backendHealth?.graphitiEmbeddingModelOptions)
    ? backendHealth.graphitiEmbeddingModelOptions
    : ["text-embedding-3-large"];
  const selectedGraphBackend = String(form.graphBackend ?? "").trim().toLowerCase();
  const isGraphitiBackend = selectedGraphBackend === "neo4j" || selectedGraphBackend === "oracle";
  const isOracleBackend = selectedGraphBackend === "oracle";
  const canShowRuntimeControls = selectedGraphBackend !== "zep_cloud";
  const enableOracleRuntimeOverrides = Boolean(form.enableOracleRuntimeOverrides);
  const resolvedGraphitiEmbeddingModel =
    String(form.graphitiEmbeddingModel ?? "").trim() ||
    String(backendHealth?.graphitiDefaultEmbeddingModel ?? "").trim() ||
    "text-embedding-3-large";
  const graphitiEmbeddingModelOptions = rawGraphitiEmbeddingModelOptions.includes(
    resolvedGraphitiEmbeddingModel,
  )
    ? rawGraphitiEmbeddingModelOptions
    : [resolvedGraphitiEmbeddingModel, ...rawGraphitiEmbeddingModelOptions];
  const activeTopPromptLabelEditorTab = String(promptLabelEditor.activeTab ?? "ontology_prompt").trim();
  const activeNodeEdgesEditorTab = String(
    promptLabelEditor.nodeEdgesEditorTab ?? "entity_edge_generator_prompt",
  ).trim();
  const activePromptLabelEditorTab =
    activeTopPromptLabelEditorTab === "node_edges"
      ? activeNodeEdgesEditorTab
      : activeTopPromptLabelEditorTab;
  const ontologyStatusLineText =
    ontologyTask.status === "running"
      ? hasOntologyStartedAtMs
        ? `${ontologyTask.message} (running for ${ontologyRunSeconds}s; polling every ${taskPollIntervalSeconds}s)`
        : `${ontologyTask.message} (polling every ${taskPollIntervalSeconds}s)`
      : ontologyTask.message;
  const graphStatusLineText =
    graphTask.status === "running"
      ? hasGraphStartedAtMs
        ? form.refreshDataWhileBuild
          ? `${graphTask.message} (running for ${graphRunSeconds}s; polling every ${graphPollIntervalSeconds}s)`
          : `${graphTask.message} (running for ${graphRunSeconds}s; polling paused)`
        : form.refreshDataWhileBuild
          ? `${graphTask.message} (polling every ${graphPollIntervalSeconds}s)`
          : `${graphTask.message} (polling paused)`
      : graphTask.message;
  const canGenerateFromLlmWithProjectState = hasSelectedProject || hasSelectedUploadFiles;
  const canGenerateFromLlm =
    activeTopPromptLabelEditorTab === "node_edges" && canGenerateFromLlmWithProjectState;
  const generateFromLlmHelpText =
    activeTopPromptLabelEditorTab !== "node_edges"
      ? "Generate From LLM is only available in Node/Edges Extraction tab."
      : hasUploadedProjectDocuments
        ? "Generate type lists from uploaded project documents."
        : hasSelectedProject
          ? hasSelectedUploadFiles
            ? "Project has no uploaded docs yet. Run Step A first, then try Generate From LLM."
            : "Generate uses uploaded project docs. If docs are missing, run Step A first."
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

  const copyEndpointUrl = async (path) => {
    const absoluteUrl = buildAbsoluteApiUrl(path);
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(absoluteUrl);
      } else {
        const helper = document.createElement("textarea");
        helper.value = absoluteUrl;
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        document.body.removeChild(helper);
      }
      if (copyEndpointToastTimerRef.current) {
        window.clearTimeout(copyEndpointToastTimerRef.current);
      }
      setCopiedEndpointPath(String(path ?? ""));
      copyEndpointToastTimerRef.current = window.setTimeout(() => {
        setCopiedEndpointPath("");
        copyEndpointToastTimerRef.current = null;
      }, 1200);
      addSystemLog(`Copied endpoint URL: ${absoluteUrl}`);
    } catch {
      addSystemLog(`Failed to copy endpoint URL: ${absoluteUrl}`);
    }
  };

  const updateOracleRuntimeField = (field, value) => {
    const raw = String(value ?? "").trim();
    if (!raw) {
      setFormField(field, "");
      return;
    }
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return;
    setFormField(field, String(Math.max(1, Math.floor(parsed))));
  };

  useEffect(() => {
    return () => {
      if (copyEndpointToastTimerRef.current) {
        window.clearTimeout(copyEndpointToastTimerRef.current);
        copyEndpointToastTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (ontologyTask.status !== "running") {
      return undefined;
    }
    setOntologyElapsedNowMs(Date.now());
    const timer = window.setInterval(() => {
      setOntologyElapsedNowMs(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [ontologyTask.status, ontologyTask.startedAt]);

  useEffect(() => {
    if (graphTask.status !== "running") {
      return undefined;
    }
    setGraphElapsedNowMs(Date.now());
    const timer = window.setInterval(() => {
      setGraphElapsedNowMs(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [graphTask.status, graphTask.startedAt]);

  const handleOntologySubmit = async (event) => {
    event.preventDefault();
    await runOntologyGenerate();
  };

  const openPromptLabelEditor = (labelName) => {
    const normalized = String(labelName ?? "").trim();
    if (!normalized) return;
    setPromptLabelDropdownOpen(false);
    setPromptLabelEditor({
      open: true,
      labelName: normalized,
      isNewLabel: false,
      activeTab: "ontology_prompt",
      nodeEdgesEditorTab: "entity_edge_generator_prompt",
      loadingTypes: true,
      loadingPromptTemplate: false,
      savingTypes: false,
      typesDraftTouched: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      promptTemplateDrafts: createEmptyPromptTemplateDrafts(),
      promptTemplateDraftTouched: createEmptyPromptTemplateTouchedState(),
      promptTemplateDraftLoaded: createEmptyPromptTemplateLoadedState(),
      promptTemplateHeights: createDefaultPromptTemplateHeights(),
      promptTemplatePreviewModes: createDefaultPromptTemplatePreviewModes(),
      collapsedTypeSections: createPromptLabelTypeCollapseState(),
      keepRemainingOnGenerate: false,
      syncing: false,
      generatingFromLlm: false,
      updatingPromptTemplateKey: "",
      notice: "",
      error: "",
    });
  };

  const openNewPromptLabelEditor = () => {
    setPromptLabelDropdownOpen(false);
    setPromptLabelEditor({
      open: true,
      labelName: "",
      isNewLabel: true,
      activeTab: "ontology_prompt",
      nodeEdgesEditorTab: "entity_edge_generator_prompt",
      loadingTypes: false,
      loadingPromptTemplate: false,
      savingTypes: false,
      typesDraftTouched: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      promptTemplateDrafts: createEmptyPromptTemplateDrafts(),
      promptTemplateDraftTouched: createEmptyPromptTemplateTouchedState(),
      promptTemplateDraftLoaded: createEmptyPromptTemplateLoadedState(),
      promptTemplateHeights: createDefaultPromptTemplateHeights(),
      promptTemplatePreviewModes: createDefaultPromptTemplatePreviewModes(),
      collapsedTypeSections: createPromptLabelTypeCollapseState(),
      keepRemainingOnGenerate: false,
      syncing: false,
      generatingFromLlm: false,
      updatingPromptTemplateKey: "",
      notice: "",
      error: "",
    });
  };

  const closePromptLabelEditor = () => {
    if (
      promptLabelEditor.syncing ||
      promptLabelEditor.savingTypes ||
      promptLabelEditor.generatingFromLlm ||
      promptLabelEditor.loadingPromptTemplate ||
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
      savingTypes: false,
      typesDraftTouched: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      promptTemplateDrafts: createEmptyPromptTemplateDrafts(),
      promptTemplateDraftTouched: createEmptyPromptTemplateTouchedState(),
      promptTemplateDraftLoaded: createEmptyPromptTemplateLoadedState(),
      promptTemplateHeights: createDefaultPromptTemplateHeights(),
      promptTemplatePreviewModes: createDefaultPromptTemplatePreviewModes(),
      collapsedTypeSections: createPromptLabelTypeCollapseState(),
      keepRemainingOnGenerate: false,
      syncing: false,
      generatingFromLlm: false,
      updatingPromptTemplateKey: "",
      notice: "",
      error: "",
    });
  };

  const updatePromptLabelTypeListDraft = (typeName, nextValues) => {
    if (!PROMPT_LABEL_TYPE_FIELDS.includes(typeName)) {
      return;
    }
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
      await updatePromptLabelPromptTemplate(labelName, activeTab, content, {
        projectId: normalizedCurrentProjectId,
      });
      await fetchPromptLabels({ syncFormLabel: false, skipDedup: true });
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
        error: "",
        notice: "Prompt updated.",
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

  const syncPromptLabelContent = async () => {
    if (promptLabelEditor.generatingFromLlm || promptLabelEditor.savingTypes) return;
    const activeTopTab = String(promptLabelEditor.activeTab ?? "node_edges").trim();
    const activeNodeEdgesTab = String(
      promptLabelEditor.nodeEdgesEditorTab ?? "entity_edge_generator_prompt",
    ).trim();
    const activeTab = activeTopTab === "node_edges" ? activeNodeEdgesTab : activeTopTab;
    const isPromptTab = isPromptTemplateTab(activeTab);

    if (isPromptTab) {
      const labelName = String(promptLabelEditor.labelName ?? "").trim();
      if (!labelName && !promptLabelEditor.isNewLabel) {
        setPromptLabelEditor((current) => ({
          ...current,
          error: "Label name is required.",
          notice: "",
        }));
        return;
      }

      setPromptLabelEditor((current) => ({
        ...current,
        syncing: true,
        loadingPromptTemplate: true,
        error: "",
        notice: "",
      }));

      try {
        if (promptLabelEditor.isNewLabel) {
          const defaultPrompt = await getPromptLabelPromptTemplate("Production", activeTab);
          setPromptLabelEditor((current) => ({
            ...current,
            syncing: false,
            loadingPromptTemplate: false,
            promptTemplateDrafts: {
              ...current.promptTemplateDrafts,
              [activeTab]: String(defaultPrompt?.content ?? ""),
            },
            promptTemplateDraftTouched: {
              ...current.promptTemplateDraftTouched,
              [activeTab]: false,
            },
            promptTemplateDraftLoaded: {
              ...current.promptTemplateDraftLoaded,
              [activeTab]: true,
            },
            error: "",
            notice: "Loaded Production default for current tab. Save to apply changes.",
          }));
          return;
        }

        const synced = await syncPromptLabelPromptTemplateFromDefault(labelName, activeTab, {
          projectId: normalizedCurrentProjectId,
        });
        await fetchPromptLabels({ syncFormLabel: false, skipDedup: true });
        setPromptLabelEditor((current) => ({
          ...current,
          syncing: false,
          loadingPromptTemplate: false,
          promptTemplateDrafts: {
            ...current.promptTemplateDrafts,
            [activeTab]: String(synced?.content ?? ""),
          },
          promptTemplateDraftTouched: {
            ...current.promptTemplateDraftTouched,
            [activeTab]: false,
          },
          promptTemplateDraftLoaded: {
            ...current.promptTemplateDraftLoaded,
            [activeTab]: true,
          },
          error: "",
          notice: "Synced current tab from label defaults.",
        }));
      } catch (error) {
        setPromptLabelEditor((current) => ({
          ...current,
          syncing: false,
          loadingPromptTemplate: false,
          notice: "",
          error: String(error),
        }));
      }
      return;
    }

    setPromptLabelEditor((current) => ({
      ...current,
      syncing: true,
      loadingTypes: true,
      error: "",
      notice: "",
    }));
    try {
      const normalizedLabelName = String(promptLabelEditor.labelName ?? "").trim();
      const sourceLabelName = promptLabelEditor.isNewLabel
        ? "Production"
        : normalizedLabelName || "Production";
      const typeResult = await getPromptLabelTypeLists(sourceLabelName);
      setPromptLabelEditor((current) => ({
        ...current,
        syncing: false,
        loadingTypes: false,
        typesDraftTouched: false,
        typeLists: normalizePromptLabelTypeListsPayload(typeResult?.types),
        error: "",
        notice: "Synced Node/Edges Extraction content from label defaults. Save to apply changes.",
      }));
    } catch (error) {
      setPromptLabelEditor((current) => ({
        ...current,
        syncing: false,
        loadingTypes: false,
        notice: "",
        error: String(error),
      }));
    }
  };

  const generatePromptLabelContentFromLlm = async () => {
    if (String(promptLabelEditor.activeTab ?? "").trim() !== "node_edges") {
      setPromptLabelEditor((current) => ({
        ...current,
        error: "Generate From LLM is only available in Node/Edges Extraction tab.",
        notice: "",
      }));
      return;
    }
    const labelName = String(promptLabelEditor.labelName ?? "").trim();
    if (!labelName) {
      setPromptLabelEditor((current) => ({
        ...current,
        error: "Label name is required.",
        notice: "",
      }));
      return;
    }

    let projectId = String(form.projectId ?? "").trim();
    const isExistingProject = Boolean(projectId);
    if (!projectId && !hasSelectedUploadFiles) {
      setPromptLabelEditor((current) => ({
        ...current,
        error: "Select a project or choose files first so a draft project can be created.",
        notice: "",
      }));
      return;
    }
    if (isExistingProject && !hasUploadedProjectDocuments) {
      setPromptLabelEditor((current) => ({
        ...current,
        error: hasSelectedUploadFiles
          ? "Run Step A first to upload the selected file(s), then try Generate From LLM again."
          : "Choose at least one file in Step A, run Ontology Generate, then try Generate From LLM.",
        notice: "",
      }));
      return;
    }

    setPromptLabelEditor((current) => ({
      ...current,
      generatingFromLlm: true,
      error: "",
      notice: "",
    }));
    try {
      const entityEdgeGeneratorPromptOverride = promptLabelEditor?.promptTemplateDraftTouched
        ?.entity_edge_generator_prompt
        ? String(promptLabelEditor?.promptTemplateDrafts?.entity_edge_generator_prompt ?? "")
        : undefined;

      if (!projectId) {
        setPromptLabelEditor((current) => ({
          ...current,
          notice: "Preparing draft project from selected files...",
          error: "",
        }));
        const draftProject = await createDraftProject({
          projectName: form.projectName,
          promptLabel: form.promptLabel,
          graphBackend: form.graphBackend,
          usePdfPageRange: form.usePdfPageRange,
          pdfPageFrom: form.pdfPageFrom,
          pdfPageTo: form.pdfPageTo,
          files: form.files,
        });
        const draftProjectId = String(draftProject?.project_id ?? "").trim();
        if (!draftProjectId) {
          throw new Error("Draft project id is missing");
        }
        projectId = draftProjectId;
        await switchProject(projectId, draftProject?.project_workspace_id ?? "");
      }

      const generatedResult = await generatePromptLabelTypeListsFromLlm(labelName, {
        projectId,
        usePdfPageRange: form.usePdfPageRange,
        pdfPageFrom: form.pdfPageFrom,
        pdfPageTo: form.pdfPageTo,
        entityEdgeGeneratorPromptContent: entityEdgeGeneratorPromptOverride,
      });
      const processedDocuments = Number(generatedResult?.processed_documents ?? 0);
      const generatedTypeLists = normalizePromptLabelTypeListsPayload(generatedResult?.types);
      setPromptLabelEditor((current) => ({
        ...current,
        generatingFromLlm: false,
        loadingTypes: false,
        typesDraftTouched: false,
        typeLists: current.keepRemainingOnGenerate
          ? mergePromptLabelTypeLists(current.typeLists, generatedTypeLists)
          : generatedTypeLists,
        error: "",
        notice: current.keepRemainingOnGenerate
          ? `Generated from LLM using ${processedDocuments} document${processedDocuments === 1 ? "" : "s"} and kept existing loaded items. Review and save.`
          : `Generated from LLM using ${processedDocuments} document${processedDocuments === 1 ? "" : "s"}. Review and save.`,
      }));
    } catch (error) {
      setPromptLabelEditor((current) => ({
        ...current,
        generatingFromLlm: false,
        loadingTypes: false,
        notice: "",
        error: String(error),
      }));
    }
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
      const existingLabels = new Set(
        promptLabelItems
          .map((item) => String(item?.display_name ?? item?.name ?? "").trim().toLowerCase())
          .filter(Boolean),
      );
    if (promptLabelEditor.isNewLabel && existingLabels.has(labelName.toLowerCase())) {
      setPromptLabelEditor((current) => ({
        ...current,
        error: `Category label '${labelName}' already exists. Select it from dropdown to edit.`,
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
        await updatePromptLabelPromptTemplate(labelName, activeTab, content, {
          projectId: normalizedCurrentProjectId,
        });
      } else {
        const payload = normalizePromptLabelTypeListsPayload(promptLabelEditor.typeLists);
        const hasCustomTypeListData = PROMPT_LABEL_TYPE_FIELDS.some(
          (field) => Array.isArray(payload[field]) && payload[field].length > 0,
        );
        let payloadToSave = payload;

        if (promptLabelEditor.isNewLabel && !hasCustomTypeListData) {
          const productionTypes = await getPromptLabelTypeLists("Production");
          payloadToSave = normalizePromptLabelTypeListsPayload(productionTypes?.types);
        }
        await updatePromptLabelTypeLists(labelName, payloadToSave, {
          projectId: promptLabelEditor.isNewLabel ? "" : normalizedCurrentProjectId,
        });
      }

      await fetchPromptLabels({ syncFormLabel: false, skipDedup: true });
      if (promptLabelEditor.isNewLabel) {
        await setProjectPromptLabel(labelName, { forceExact: true });
      }

      addSystemLog(
        promptLabelEditor.isNewLabel
          ? `Category label created and applied: ${labelName}`
          : `Category label saved: ${labelName}`,
      );
      setPromptLabelEditor({
        open: false,
        labelName: "",
        isNewLabel: false,
        activeTab: "ontology_prompt",
        nodeEdgesEditorTab: "entity_edge_generator_prompt",
        loadingTypes: false,
        loadingPromptTemplate: false,
        savingTypes: false,
        typesDraftTouched: false,
        typeLists: createEmptyPromptLabelTypeLists(),
        promptTemplateDrafts: createEmptyPromptTemplateDrafts(),
        promptTemplateDraftTouched: createEmptyPromptTemplateTouchedState(),
        promptTemplateDraftLoaded: createEmptyPromptTemplateLoadedState(),
        promptTemplateHeights: createDefaultPromptTemplateHeights(),
        promptTemplatePreviewModes: createDefaultPromptTemplatePreviewModes(),
        collapsedTypeSections: createPromptLabelTypeCollapseState(),
        keepRemainingOnGenerate: false,
        syncing: false,
        generatingFromLlm: false,
        updatingPromptTemplateKey: "",
        notice: "",
        error: "",
      });
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
    if (promptLabelEditor.syncing || promptLabelEditor.savingTypes || promptLabelEditor.generatingFromLlm) {
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
      error: "",
      notice: "",
    }));
    try {
      if (isPromptTab) {
        const normalizedLabelName = String(promptLabelEditor.labelName ?? "").trim();
        const sourceLabelName = promptLabelEditor.isNewLabel
          ? "Production"
          : normalizedLabelName || "Production";
        const defaultPrompt = await getPromptLabelPromptTemplate(sourceLabelName, activeTab);
        setPromptLabelEditor((current) => ({
          ...current,
          loadingTypes: false,
          loadingPromptTemplate: false,
          promptTemplateDrafts: {
            ...current.promptTemplateDrafts,
            [activeTab]: String(defaultPrompt?.content ?? ""),
          },
          promptTemplateDraftTouched: {
            ...current.promptTemplateDraftTouched,
            [activeTab]: false,
          },
          promptTemplateDraftLoaded: {
            ...current.promptTemplateDraftLoaded,
            [activeTab]: true,
          },
          error: "",
          notice: "Reverted current tab to label defaults. Save to apply changes.",
        }));
        return;
      }

      const normalizedLabelName = String(promptLabelEditor.labelName ?? "").trim();
      const sourceLabelName = promptLabelEditor.isNewLabel
        ? "Production"
        : normalizedLabelName || "Production";
      const defaultTypeLists = await getPromptLabelTypeLists(sourceLabelName);
      setPromptLabelEditor((current) => ({
        ...current,
        loadingTypes: false,
        loadingPromptTemplate: false,
        typesDraftTouched: false,
        typeLists: normalizePromptLabelTypeListsPayload(defaultTypeLists?.types),
        error: "",
        notice: "Reverted Node/Edges Extraction content to label defaults. Save to apply changes.",
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

  const closeTypePropertyEditor = () => {
    setTypePropertyEditor({
      open: false,
      mode: "",
      sourceList: "draft",
      index: -1,
      draft: null,
      jsonTexts: {},
      invalidJsonIndexes: {},
      error: "",
    });
  };

  const openTypePropertyEditor = (mode, index, sourceList = "draft") => {
    const fromOriginal = sourceList === "original";
    const sourceDefinitions =
      mode === "entity"
        ? fromOriginal
          ? originalEntityTypes
          : draftEntityTypes
        : fromOriginal
          ? originalEdgeTypes
          : draftEdgeTypes;
    const source = sourceDefinitions[index];
    if (!source) return;

    const safeDraft = clonePlainData(source);
    const toJsonText = (item) => {
      try {
        return JSON.stringify(item);
      } catch {
        return "{}";
      }
    };
    setTypePropertyEditor({
      open: true,
      mode,
      sourceList: fromOriginal ? "original" : "draft",
      index,
      draft: safeDraft,
      jsonTexts: {
        attributes: Array.isArray(safeDraft.attributes) ? safeDraft.attributes.map(toJsonText) : [],
        source_targets:
          mode === "relationship" && Array.isArray(safeDraft.source_targets)
            ? safeDraft.source_targets.map(toJsonText)
            : [],
      },
      invalidJsonIndexes: {},
      error: "",
    });
  };

  const updateTypePropertyDraftField = (field, value) => {
    setTypePropertyEditor((current) => ({
      ...current,
      draft: current?.draft ? { ...current.draft, [field]: value } : current.draft,
      error: "",
    }));
  };

  const updateTypePropertyJsonField = (field, values) => {
    setTypePropertyEditor((current) => ({
      ...current,
      jsonTexts: {
        ...current.jsonTexts,
        [field]: values,
      },
      invalidJsonIndexes: {
        ...current.invalidJsonIndexes,
        [field]: [],
      },
      error: "",
    }));
  };

  const normalizeSourceTargetRowValue = (value) => {
    try {
      const parsed = JSON.parse(String(value ?? ""));
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return { source: "", target: "" };
      }
      return {
        source: String(parsed.source ?? ""),
        target: String(parsed.target ?? ""),
      };
    } catch {
      return { source: "", target: "" };
    }
  };

  const updateSourceTargetRow = (index, field, value) => {
    const currentValues = Array.isArray(typePropertyEditor.jsonTexts?.source_targets)
      ? typePropertyEditor.jsonTexts.source_targets
      : [];
    const nextValues = [...currentValues];
    const nextRow = normalizeSourceTargetRowValue(nextValues[index]);
    nextRow[field] = String(value ?? "");
    nextValues[index] = JSON.stringify({
      source: nextRow.source,
      target: nextRow.target,
    });
    updateTypePropertyJsonField("source_targets", nextValues);
  };

  const removeSourceTargetRow = (index) => {
    const currentValues = Array.isArray(typePropertyEditor.jsonTexts?.source_targets)
      ? typePropertyEditor.jsonTexts.source_targets
      : [];
    updateTypePropertyJsonField(
      "source_targets",
      currentValues.filter((_, cursor) => cursor !== index),
    );
  };

  const addSourceTargetRow = () => {
    const currentValues = Array.isArray(typePropertyEditor.jsonTexts?.source_targets)
      ? typePropertyEditor.jsonTexts.source_targets
      : [];
    updateTypePropertyJsonField("source_targets", [
      ...currentValues,
      JSON.stringify({ source: "", target: "" }),
    ]);
  };

  const confirmTypePropertyEditor = () => {
    if (!typePropertyEditor.open || !typePropertyEditor.draft) return;

    const normalizedName = normalizeTypeTag(typePropertyEditor.draft.name);
    if (!normalizedName) {
      setTypePropertyEditor((current) => ({
        ...current,
        error: "Type name is required.",
      }));
      return;
    }

    const sourceDefinitions =
      typePropertyEditor.mode === "entity"
        ? typePropertyEditor.sourceList === "original"
          ? originalEntityTypes
          : draftEntityTypes
        : typePropertyEditor.sourceList === "original"
          ? originalEdgeTypes
          : draftEdgeTypes;
    const hasDuplicateName = sourceDefinitions.some(
      (item, index) =>
        index !== typePropertyEditor.index &&
        normalizeTypeKey(item?.name) === normalizeTypeKey(normalizedName),
    );
    if (hasDuplicateName) {
      setTypePropertyEditor((current) => ({
        ...current,
        error: `Type name "${normalizedName}" already exists.`,
      }));
      return;
    }

    const invalidJsonIndexes = {};
    const parseJsonField = (field) => {
      const fieldValues = Array.isArray(typePropertyEditor.jsonTexts?.[field])
        ? typePropertyEditor.jsonTexts[field]
        : [];
      const parsedValues = [];
      const invalidIndexes = [];

      fieldValues.forEach((value, index) => {
        const normalized = String(value ?? "").trim();
        if (!normalized) return;
        try {
          const parsed = JSON.parse(normalized);
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            invalidIndexes.push(index);
            return;
          }
          parsedValues.push(parsed);
        } catch {
          invalidIndexes.push(index);
        }
      });

      if (invalidIndexes.length > 0) {
        invalidJsonIndexes[field] = invalidIndexes;
      }
      return parsedValues;
    };

    const parsedAttributes = parseJsonField("attributes");
    const parsedSourceTargets =
      typePropertyEditor.mode === "relationship" ? parseJsonField("source_targets") : [];

    if (Object.keys(invalidJsonIndexes).length > 0) {
      setTypePropertyEditor((current) => ({
        ...current,
        invalidJsonIndexes,
        error: "Fix invalid JSON fields before confirming.",
      }));
      return;
    }

    const nextDraft =
      typePropertyEditor.mode === "entity"
        ? sanitizeEntityTypeDraft({
            ...typePropertyEditor.draft,
            name: normalizedName,
            description: String(typePropertyEditor.draft.description ?? ""),
            examples: normalizeStringList(typePropertyEditor.draft.examples),
            attributes: parsedAttributes,
          })
        : sanitizeRelationshipTypeDraft({
            ...typePropertyEditor.draft,
            name: normalizedName,
            description: String(typePropertyEditor.draft.description ?? ""),
            attributes: parsedAttributes,
            source_targets: parsedSourceTargets,
          });

    if (!nextDraft) {
      setTypePropertyEditor((current) => ({
        ...current,
        error: "Type draft is invalid.",
      }));
      return;
    }

    if (typePropertyEditor.mode === "entity") {
      if (typePropertyEditor.sourceList === "original") {
        setOriginalEntityTypes((current) =>
          current.map((item, index) => (index === typePropertyEditor.index ? nextDraft : item)),
        );
      } else {
        setDraftEntityTypes((current) =>
          current.map((item, index) => (index === typePropertyEditor.index ? nextDraft : item)),
        );
      }
    } else if (typePropertyEditor.sourceList === "original") {
      setOriginalEdgeTypes((current) =>
        current.map((item, index) => (index === typePropertyEditor.index ? nextDraft : item)),
      );
    } else {
      setDraftEdgeTypes((current) =>
        current.map((item, index) => (index === typePropertyEditor.index ? nextDraft : item)),
      );
    }
    closeTypePropertyEditor();
  };

  const deleteTypePropertyEditor = () => {
    if (!typePropertyEditor.open) return;
    const targetIndex = Number(typePropertyEditor.index);
    if (!Number.isInteger(targetIndex) || targetIndex < 0) return;

    if (typePropertyEditor.mode === "entity") {
      if (typePropertyEditor.sourceList === "original") {
        setOriginalEntityTypes((current) => current.filter((_, index) => index !== targetIndex));
      } else {
        setDraftEntityTypes((current) => current.filter((_, index) => index !== targetIndex));
      }
    } else if (typePropertyEditor.mode === "relationship") {
      if (typePropertyEditor.sourceList === "original") {
        setOriginalEdgeTypes((current) => current.filter((_, index) => index !== targetIndex));
      } else {
        setDraftEdgeTypes((current) => current.filter((_, index) => index !== targetIndex));
      }
    }
    closeTypePropertyEditor();
  };

  const openOntologyEditor = async (section) => {
    if (!canOpenOntologyEditor) {
      addSystemLog("Ontology editor is available after Step A finishes.");
      return;
    }
    const baselineEntityTypes = extractOntologyTypeDrafts(currentProject, "entity_types", "entity");
    const baselineEdgeTypes = extractOntologyTypeDrafts(currentProject, "edge_types", "relationship");
    setOntologyEditorOpen(true);
    setOntologyEditorTab(section);
    setOntologyEditorRemoveMode({ entity: false, relationship: false });
    setOntologyMergeSelection({ entity: [], relationship: [] });
    setOntologyGeneratedDiff({ entity: false, relationship: false });
    setOntologyMergeRequired(false);
    setOriginalEntityTypes(baselineEntityTypes);
    setOriginalEdgeTypes(baselineEdgeTypes);
    setDraftEntityTypes(baselineEntityTypes);
    setDraftEdgeTypes(baselineEdgeTypes);
    setOntologyEditorError("");
    closeTypePropertyEditor();
    try {
      const rows = await fetchProjectOntologyVersions(form.projectId, 50);
      setOntologyVersions(rows);
      const latestGenerated = rows.find((row) => String(row?.source ?? "").toLowerCase() === "generated");
      if (latestGenerated?.ontology_json) {
        const generatedEntityTypes = extractOntologyTypeDrafts(
          { ontology: latestGenerated.ontology_json },
          "entity_types",
          "entity",
        );
        const generatedEdgeTypes = extractOntologyTypeDrafts(
          { ontology: latestGenerated.ontology_json },
          "edge_types",
          "relationship",
        );
        const nextDraftEntityTypes =
          generatedEntityTypes.length > 0 ? generatedEntityTypes : baselineEntityTypes;
        const nextDraftEdgeTypes = generatedEdgeTypes.length > 0 ? generatedEdgeTypes : baselineEdgeTypes;
        const hasEntityGeneratedDiff =
          generatedEntityTypes.length > 0 &&
          !areTypeDefinitionListsEquivalent(baselineEntityTypes, generatedEntityTypes, "entity");
        const hasRelationshipGeneratedDiff =
          generatedEdgeTypes.length > 0 &&
          !areTypeDefinitionListsEquivalent(baselineEdgeTypes, generatedEdgeTypes, "relationship");
        setDraftEntityTypes(nextDraftEntityTypes);
        setDraftEdgeTypes(nextDraftEdgeTypes);
        setOntologyGeneratedDiff({
          entity: hasEntityGeneratedDiff,
          relationship: hasRelationshipGeneratedDiff,
        });
        setOntologyMergeRequired(hasEntityGeneratedDiff || hasRelationshipGeneratedDiff);
      }
    } catch (error) {
      addSystemLog(`Failed to load ontology versions: ${String(error)}`);
      setOntologyVersions([]);
    }
  };

  const closeOntologyEditor = () => {
    if (savingOntologyTypes) return;
    setOntologyEditorOpen(false);
    setOntologyEditorTab("entity");
    setOntologyEditorRemoveMode({ entity: false, relationship: false });
    setOntologyMergeSelection({ entity: [], relationship: [] });
    setOntologyVersions([]);
    setOntologyEditorError("");
    closeTypePropertyEditor();
  };

  const revertOntologyEditorDraft = () => {
    if (!ontologyEditorOpen || savingOntologyTypes) return;
    setDraftEntityTypes(extractOntologyTypeDrafts(currentProject, "entity_types", "entity"));
    setDraftEdgeTypes(extractOntologyTypeDrafts(currentProject, "edge_types", "relationship"));
    setOntologyGeneratedDiff({ entity: false, relationship: false });
    setOntologyMergeRequired(false);
    setOntologyEditorRemoveMode({ entity: false, relationship: false });
    setOntologyMergeSelection({ entity: [], relationship: [] });
    setOntologyEditorError("");
    closeTypePropertyEditor();
  };

  const confirmOntologyEditor = async () => {
    if (ontologyMergeRequired) {
      setOntologyEditorError("Click Merge Matching before Confirm.");
      return;
    }
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
        entityTypes: draftEntityTypes,
        edgeTypes: draftEdgeTypes,
        preserveGraphStatus: true,
      });
      setOntologyEditorOpen(false);
      setOntologyEditorTab("entity");
      setOntologyEditorRemoveMode({ entity: false, relationship: false });
      setOntologyMergeSelection({ entity: [], relationship: [] });
      setOntologyGeneratedDiff({ entity: false, relationship: false });
      setOntologyMergeRequired(false);
      setOntologyVersions([]);
      closeTypePropertyEditor();
    } catch (error) {
      const message = String(error);
      setOntologyEditorError(message);
      addSystemLog(`Failed to update ontology types: ${message}`);
    } finally {
      setSavingOntologyTypes(false);
    }
  };

  const handleEntityTagNamesChange = (nextNames) => {
    setDraftEntityTypes((current) => remapTypeDefinitions(current, nextNames, "entity"));
    setOntologyMergeSelection((current) => ({ ...current, entity: [] }));
  };

  const handleRelationshipTagNamesChange = (nextNames) => {
    setDraftEdgeTypes((current) => remapTypeDefinitions(current, nextNames, "relationship"));
    setOntologyMergeSelection((current) => ({ ...current, relationship: [] }));
  };

  const handleOriginalEntityTagNamesChange = (nextNames) => {
    setOriginalEntityTypes((current) => remapTypeDefinitions(current, nextNames, "entity"));
  };

  const handleOriginalRelationshipTagNamesChange = (nextNames) => {
    setOriginalEdgeTypes((current) => remapTypeDefinitions(current, nextNames, "relationship"));
  };

  const toggleOntologyTypeSelection = (mode, index) => {
    setOntologyMergeSelection((current) => {
      const currentValues = Array.isArray(current?.[mode]) ? current[mode] : [];
      const alreadySelected = currentValues.includes(index);
      return {
        ...current,
        [mode]: alreadySelected
          ? currentValues.filter((value) => value !== index)
          : [...currentValues, index],
      };
    });
  };

  const mergeSelectedDraftTypes = (mode) => {
    const selectedIndexes = Array.isArray(ontologyMergeSelection?.[mode])
      ? ontologyMergeSelection[mode]
      : [];
    if (selectedIndexes.length < 2) return;
    const targetIndex = selectedIndexes[0];
    const selectedIndexSet = new Set(selectedIndexes);
    const applyMerge = (types) => {
      const currentTypes = Array.isArray(types) ? types : [];
      const target = currentTypes[targetIndex];
      if (!target) return currentTypes;
      let mergedTarget = target;
      selectedIndexes.slice(1).forEach((index) => {
        const incoming = currentTypes[index];
        if (!incoming) return;
        mergedTarget = mergeTypeDefinition(mergedTarget, incoming, mode === "entity" ? "entity" : "relationship");
      });
      return currentTypes
        .map((item, index) => (index === targetIndex ? mergedTarget : item))
        .filter((_, index) => !selectedIndexSet.has(index) || index === targetIndex);
    };
    if (mode === "entity") {
      setDraftEntityTypes((current) => applyMerge(current));
    } else {
      setDraftEdgeTypes((current) => applyMerge(current));
    }
    setOntologyMergeSelection((current) => ({ ...current, [mode]: [] }));
  };

  const mergeMatchingTypesFromOriginal = () => {
    setDraftEntityTypes((current) =>
      current.map((item) => {
        const baseline = findTypeDefinitionByName(originalEntityTypes, item?.name);
        if (!baseline) return item;
        return mergeTypeDefinition(baseline, item, "entity");
      }),
    );
    setDraftEdgeTypes((current) =>
      current.map((item) => {
        const baseline = findTypeDefinitionByName(originalEdgeTypes, item?.name);
        if (!baseline) return item;
        return mergeTypeDefinition(baseline, item, "relationship");
      }),
    );
    setOntologyMergeSelection({ entity: [], relationship: [] });
    setOntologyMergeRequired(false);
    setOntologyEditorError("");
  };

  const handleOntologyStatBoxKeyDown = (event, section) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openOntologyEditor(section);
  };

  const handleGraphTabClick = () => {
    if (!stepBUnlocked || ontologyMergeRequired) {
      // addSystemLog("Step B is locked until Step A finishes ontology generation.");
      return;
    }
    setActiveStepTab("B");
  };

  useEffect(() => {
    if (!promptLabelDropdownOpen) return undefined;

    const onPointerDown = (event) => {
      if (!promptLabelDropdownRef.current?.contains(event.target)) {
        setPromptLabelDropdownOpen(false);
      }
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        setPromptLabelDropdownOpen(false);
      }
    };

    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [promptLabelDropdownOpen]);

  useEffect(() => {
    const labelName = String(promptLabelEditor.labelName ?? "").trim();
    if (!promptLabelEditor.open || promptLabelEditor.isNewLabel || !labelName) return undefined;

    let cancelled = false;
    setPromptLabelEditor((current) => ({
      ...current,
      loadingTypes: true,
      error: "",
    }));

    getPromptLabelTypeLists(labelName, { projectId: normalizedCurrentProjectId })
      .then((result) => {
        if (cancelled) return;
        setPromptLabelEditor((current) => {
          const currentLabel = String(current.labelName ?? "").trim().toLowerCase();
          if (!current.open || currentLabel !== labelName.toLowerCase()) {
            return current;
          }
          return {
            ...current,
            loadingTypes: false,
            typeLists: current.typesDraftTouched
              ? current.typeLists
              : normalizePromptLabelTypeListsPayload(result?.types),
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
  }, [
    promptLabelEditor.open,
    promptLabelEditor.isNewLabel,
    promptLabelEditor.labelName,
    normalizedCurrentProjectId,
  ]);

  useEffect(() => {
    if (!promptLabelEditor.open) return undefined;
    const activeTopTab = String(promptLabelEditor.activeTab ?? "").trim();
    const activeNodeEdgesTab = String(
      promptLabelEditor.nodeEdgesEditorTab ?? "entity_edge_generator_prompt",
    ).trim();
    const activeTab = activeTopTab === "node_edges" ? activeNodeEdgesTab : activeTopTab;
    if (!isPromptTemplateTab(activeTab)) return undefined;
    if (promptLabelEditor?.promptTemplateDraftLoaded?.[activeTab]) {
      return undefined;
    }

    const normalizedLabelName = String(promptLabelEditor.labelName ?? "").trim();
    const requestLabelName =
      promptLabelEditor.isNewLabel || !normalizedLabelName ? "Production" : normalizedLabelName;

    let cancelled = false;
    setPromptLabelEditor((current) => ({
      ...current,
      loadingPromptTemplate: true,
      error: "",
    }));

    getPromptLabelPromptTemplate(requestLabelName, activeTab, {
      projectId: promptLabelEditor.isNewLabel ? "" : normalizedCurrentProjectId,
    })
      .then((result) => {
        if (cancelled) return;
        setPromptLabelEditor((current) => {
          const currentTopTab = String(current.activeTab ?? "").trim();
          const currentNodeEdgesTab = String(
            current.nodeEdgesEditorTab ?? "entity_edge_generator_prompt",
          ).trim();
          const currentActiveTab =
            currentTopTab === "node_edges" ? currentNodeEdgesTab : currentTopTab;
          if (!current.open || currentActiveTab !== activeTab) {
            return current;
          }
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
    normalizedCurrentProjectId,
  ]);

  useEffect(() => {
    if (!isTypePropertyEditorOpen && !promptLabelEditor.open && !ontologyEditorOpen) {
      return undefined;
    }

    const onKeyDown = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();

      if (isTypePropertyEditorOpen) {
        closeTypePropertyEditor();
        return;
      }
      if (promptLabelEditor.open) {
        closePromptLabelEditor();
        return;
      }
      if (ontologyEditorOpen) {
        closeOntologyEditor();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [
    isTypePropertyEditorOpen,
    promptLabelEditor.open,
    promptLabelEditor.syncing,
    promptLabelEditor.savingTypes,
    promptLabelEditor.generatingFromLlm,
    ontologyEditorOpen,
    savingOntologyTypes,
  ]);

  useEffect(() => {
    if (!logContainerRef.current) return;
    logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
  }, [systemLogs.length, activeBackendTab]);

  useEffect(() => {
    if (activeStepTab === "B" && (!stepBUnlocked || ontologyMergeRequired)) {
      setActiveStepTab("A");
    }
  }, [activeStepTab, stepBUnlocked, ontologyMergeRequired]);

  useEffect(() => {
    setOntologyGeneratedDiff({ entity: false, relationship: false });
    setOntologyMergeRequired(false);
  }, [normalizedCurrentProjectId]);

  useEffect(() => {
    if (isGraphTaskRunning) {
      if (activeStepTab !== "B") {
        setActiveStepTab("B");
      }
      return;
    }
    if (isOntologyTaskRunning && activeStepTab !== "A") {
      setActiveStepTab("A");
    }
  }, [activeStepTab, isGraphTaskRunning, isOntologyTaskRunning]);

  const typePropertyDraft = typePropertyEditor.draft ?? {};
  const typePropertyTargetLabel =
    typePropertyEditor.sourceList === "original" ? "Original" : "New / Generated";
  const typePropertyModeLabel =
    typePropertyEditor.mode === "entity" ? "Entity Type Properties" : "Relationship Type Properties";
  const typePropertyDescription =
    typePropertyEditor.mode === "entity"
      ? `${typePropertyTargetLabel} list: edit name, description, metadata string list, and attribute JSON payloads.`
      : `${typePropertyTargetLabel} list: edit name, description, attribute JSON payloads, and source-target pairs.`;
  const editingPromptLabelMeta = promptLabelCatalog.items.find(
    (item) =>
      String(item?.display_name ?? item?.name ?? "").trim().toLowerCase() ===
      String(promptLabelEditor.labelName ?? "").trim().toLowerCase(),
  );

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
                className={`step-tab ${activeStepTab === "B" ? "active" : ""} ${!stepBUnlocked || ontologyMergeRequired ? "disabled" : ""}`}
                type="button"
                onClick={handleGraphTabClick}
              >
                Step B - Graph Build
              </button>
            </div>

            {activeStepTab === "A" && (
              <article className="step-card">
                <div className="card-head">
                  <h2 className="step-title">Ontology Generate</h2>
                  <div className="card-head-meta">
                    <button
                      className="endpoint endpoint-copy-btn"
                      type="button"
                      onClick={() => copyEndpointUrl("/api/ontology/generate")}
                      title={`Click to copy ${buildAbsoluteApiUrl("/api/ontology/generate")}`}
                    >
                      POST /api/ontology/generate
                      {copiedEndpointPath === "/api/ontology/generate" && (
                        <span className="endpoint-copy-popup" role="status" aria-live="polite">
                          Copy!
                        </span>
                      )}
                    </button>
                    <span className={`badge ${statusClass(ontologyTask.status)}`}>{ontologyTask.status}</span>
                    <span
                      className="card-info-icon"
                      role="img"
                      aria-label="Ontology step information"
                      data-tooltip="Upload files and generate ontology schema for the project."
                      title="Upload files and generate ontology schema for the project."
                    >
                      ⓘ
                    </span>
                  </div>
                </div>

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
                    <div className="field-head">
                      <span>Project Name</span>
                      <div className="field-head-actions">
                        <span className="field-head-inline-checkbox">
                          <input
                            type="checkbox"
                            checked={Boolean(form.useProjectNameAsGraphId)}
                            onChange={(event) =>
                              setFormField("useProjectNameAsGraphId", event.target.checked)
                            }
                            disabled={!isZepCloudBackend || isProjectCreated}
                          />
                          <span>Zep Cloud GraphID</span>
                        </span>
                        <span
                          className="card-info-icon field-info-icon"
                          role="img"
                          aria-label="Project Name information"
                          data-tooltip="Project name is locked after project creation."
                          title="Project name is locked after project creation."
                        >
                          ⓘ
                        </span>
                      </div>
                    </div>
                    <input
                      value={form.projectName}
                      onChange={(event) => setFormField("projectName", event.target.value)}
                      placeholder="Project name"
                      disabled={isProjectCreated}
                    />
                    <p className="field-note">
                      {isZepCloudBackend
                        ? "When enabled at project creation, Step B uses project name as zep_cloud graph_id."
                        : "Zep Cloud GraphID toggle is available only when backend is zep_cloud."}
                    </p>
                  </label>

                  <label className="field">
                    <span>Additional Context (optional)</span>
                    <input
                      value={form.additionalContext}
                      onChange={(event) => setFormField("additionalContext", event.target.value)}
                      placeholder="Extra instructions..."
                    />
                  </label>

                  <div className="field-row-two">
                    <label className="field">
                      <span>Minimum Nodes</span>
                      <input
                        type="number"
                        min="1"
                        step="1"
                        value={form.minimumNodes}
                        onChange={(event) => setFormField("minimumNodes", event.target.value)}
                        placeholder="10"
                      />
                    </label>
                    <label className="field">
                      <span>Minimum Edges</span>
                      <input
                        type="number"
                        min="1"
                        step="1"
                        value={form.minimumEdges}
                        onChange={(event) => setFormField("minimumEdges", event.target.value)}
                        placeholder="10"
                      />
                    </label>
                  </div>

                  <label className="field">
                    <span>Files</span>
                    <input
                      type="file"
                      multiple
                      onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
                    />
                  </label>
                  <label className="field checkbox-field">
                    <span className="field-toggle-row">
                      <span>Limit PDF page range</span>
                      <span className="toggle-switch toggle-switch-green">
                        <input
                          type="checkbox"
                          checked={Boolean(form.usePdfPageRange)}
                          onChange={(event) => setFormField("usePdfPageRange", event.target.checked)}
                        />
                        <span className="slider" />
                      </span>
                    </span>
                    <p className="field-note">
                      Off = parse full PDF. On = only parse selected page range below.
                    </p>
                  </label>
                  {Boolean(form.usePdfPageRange) && (
                    <>
                      <div className="field-row-two pdf-page-range-row">
                        <label className="field">
                          <span>PDF Page From</span>
                          <input
                            type="number"
                            min="1"
                            step="1"
                            value={form.pdfPageFrom}
                            onChange={(event) => setFormField("pdfPageFrom", event.target.value)}
                            placeholder="1"
                          />
                        </label>
                        <label className="field">
                          <span>PDF Page To</span>
                          <input
                            type="number"
                            min="1"
                            step="1"
                            value={form.pdfPageTo}
                            onChange={(event) => setFormField("pdfPageTo", event.target.value)}
                            placeholder="100"
                          />
                        </label>
                      </div>
                      <p className="field-note pdf-page-range-note">
                        Example: 1 to 100 reads the first 100 pages.
                      </p>
                    </>
                  )}

                  <label className="field">
                    <div className="field-head">
                      <span>Category Label</span>
                      <span
                        className="card-info-icon field-info-icon"
                        role="img"
                        aria-label="Category Label resolution information"
                        data-tooltip="Prompt resolution tries selected label first, then Production, then local prompt file."
                        title="Prompt resolution tries selected label first, then Production, then local prompt file."
                      >
                        ⓘ
                      </span>
                    </div>
                    <div className="label-dropdown" ref={promptLabelDropdownRef}>
                      <button
                        className={`label-dropdown-trigger ${promptLabelDropdownOpen ? "open" : ""}`}
                        type="button"
                        onClick={() => setPromptLabelDropdownOpen((current) => !current)}
                        aria-haspopup="listbox"
                        aria-expanded={promptLabelDropdownOpen}
                      >
                        <span className="label-dropdown-trigger-main">
                          <span>{form.promptLabel || "Production"}</span>
                          {hasCurrentProjectLabelAssociation && (
                            <span
                              className="label-dropdown-item-project-indicator label-dropdown-trigger-project-indicator"
                              aria-label="Current label is associated with this project"
                              title="Current label is associated with this project"
                            >
                              P
                            </span>
                          )}
                        </span>
                        <span className="label-dropdown-caret" aria-hidden="true">
                          ▾
                        </span>
                      </button>
                      {promptLabelDropdownOpen && (
                        <div className="label-dropdown-menu" role="listbox" aria-label="Category Label options">
                          {promptLabelItems
                            .filter((item) => String(item?.name ?? "").trim())
                            .map((item) => {
                              const labelName = String(item?.name ?? "").trim();
                              const labelDisplayName = String(item?.display_name ?? labelName).trim();
                              const itemProjectId = String(item?.project_id ?? "").trim();
                              const isSelected =
                                String(form.promptLabel ?? "").trim().toLowerCase() ===
                                labelDisplayName.toLowerCase();
                              const isProjectScoped =
                                Boolean(itemProjectId) &&
                                Boolean(normalizedCurrentProjectId) &&
                                itemProjectId.toLowerCase() === normalizedCurrentProjectId.toLowerCase();
                              return (
                                <div
                                  className={`label-dropdown-item ${isSelected ? "selected" : ""}`}
                                  key={`${labelDisplayName}-${itemProjectId || "global"}-${labelName}`}
                                  role="option"
                                  aria-selected={isSelected}
                                >
                                  <button
                                    className="label-dropdown-item-main"
                                    type="button"
                                    onClick={() => {
                                      setProjectPromptLabel(labelDisplayName);
                                      setPromptLabelDropdownOpen(false);
                                    }}
                                    title={labelDisplayName}
                                  >
                                    <span className="label-dropdown-item-name">{labelDisplayName}</span>
                                  </button>
                                  <div className="label-dropdown-item-indicators">
                                    {isSelected && (
                                      <span
                                        className="label-dropdown-item-selected-indicator"
                                        aria-label="Selected category label"
                                        title="Selected category label"
                                      >
                                        ✓
                                      </span>
                                    )}
                                    {isProjectScoped && (
                                      <span
                                        className="label-dropdown-item-project-indicator"
                                        aria-label="Project label override"
                                        title="Project label override"
                                      >
                                        P
                                      </span>
                                    )}
                                  </div>
                                  <button
                                    className="label-dropdown-item-edit"
                                    type="button"
                                    onClick={() => openPromptLabelEditor(labelDisplayName)}
                                    aria-label={`Edit label ${labelDisplayName}`}
                                    title={`Edit label ${labelDisplayName}`}
                                  >
                                    ✎
                                  </button>
                                </div>
                              );
                            })}
                          <div className="label-dropdown-item add-new">
                            <button
                              className="label-dropdown-item-main"
                              type="button"
                              onClick={openNewPromptLabelEditor}
                              title="Add new category label"
                            >
                              <span className="label-dropdown-item-name">+ Add New Label</span>
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  </label>

                  <div className="step-primary-actions">
                    <button className="action-btn" type="submit" disabled={isAnyTaskRunning}>
                      {isOntologyTaskRunning
                        ? "Generating..."
                        : isGraphTaskRunning
                          ? "Step B Running..."
                          : "Run Ontology Generate"}
                    </button>
                    {isOntologyTaskRunning && hasOntologyTaskId && (
                      <button className="ontology-editor-cancel-btn" type="button" onClick={cancelOntologyTask}>
                        Cancel
                      </button>
                    )}
                  </div>
                </form>

                <div className="progress-wrap">
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${ontologyTask.progress ?? 0}%` }} />
                  </div>
                  <span>{ontologyTask.progress ?? 0}%</span>
                </div>

                <p className="status-line">{ontologyStatusLineText}</p>
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
              <article className={`step-card ${!stepBUnlocked || ontologyMergeRequired ? "locked" : ""}`}>
                <div className="card-head">
                  <h2 className="step-title">Graph Build</h2>
                  <div className="card-head-meta">
                    <button
                      className="endpoint endpoint-copy-btn"
                      type="button"
                      onClick={() => copyEndpointUrl("/api/build")}
                      title={`Click to copy ${buildAbsoluteApiUrl("/api/build")}`}
                    >
                      POST /api/build
                      {copiedEndpointPath === "/api/build" && (
                        <span className="endpoint-copy-popup" role="status" aria-live="polite">
                          Copy!
                        </span>
                      )}
                    </button>
                    <span className={`badge ${statusClass(graphTask.status)}`}>{graphTask.status}</span>
                    <span
                      className="card-info-icon"
                      role="img"
                      aria-label="Graph build step information"
                      data-tooltip="Build graph from generated ontology and monitor task progress."
                      title="Build graph from generated ontology and monitor task progress."
                    >
                      ⓘ
                    </span>
                  </div>
                </div>
                {!stepBUnlocked && (
                  <p className="status-line warning">Step B is locked until Step A finishes successfully.</p>
                )}
                {stepBUnlocked && ontologyMergeRequired && (
                  <p className="status-line warning">
                    Step B is locked. Open ontology editor, click Merge Matching, then Confirm.
                  </p>
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
                  <span>Graph Label</span>
                  <input
                    value={form.graphLabel}
                    onChange={(event) => setFormField("graphLabel", event.target.value)}
                    placeholder="Optional graph label suffix"
                  />
                  <p className="field-note">
                    Optional suffix for graph labels (node/edge/episode) when `graph_label` exists.
                  </p>
                </label>

                <label className="field">
                  <span>Chunk Mode</span>
                  <select
                    value={form.chunkMode}
                    onChange={(event) => setFormField("chunkMode", event.target.value)}
                  >
                    <option value="fixed">Fixed</option>
                    <option value="semantic">Semantic (LLM)</option>
                    <option value="hybrid">Hybrid (Fixed + LLM)</option>
                    <option value="llama_index">LlamaIndex Semantic</option>
                  </select>
                  <p className="field-note">
                    Fixed is fastest. Semantic uses LLM boundaries. Hybrid uses fixed first then LLM only
                    when needed. LlamaIndex Semantic uses SemanticSplitterNodeParser.
                  </p>
                </label>

                <label className="field">
                  <span>Graphiti Embedding Model</span>
                  <select
                    value={resolvedGraphitiEmbeddingModel}
                    onChange={(event) => setFormField("graphitiEmbeddingModel", event.target.value)}
                    disabled={!isGraphitiBackend}
                  >
                    {graphitiEmbeddingModelOptions.map((modelName) => (
                      <option key={modelName} value={modelName}>
                        {modelName}
                      </option>
                    ))}
                  </select>
                  <p className="field-note">
                    {isGraphitiBackend
                      ? "Used by Graphiti (neo4j/oracle) during Step B embedding."
                      : "Enabled when graph backend is neo4j/oracle. Zep Cloud ignores this setting."}
                  </p>
                </label>

                {!isLlmOnlyChunkMode && (
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
                )}

                {!isLlmOnlyChunkMode && (
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
                )}

                <div className="field stepb-toggle-row">
                  <label className="stepb-toggle-item">
                    <span className="stepb-toggle-label">Override Existing Graph</span>
                    <span className="stepb-toggle-control">
                      <span className="toggle-switch toggle-switch-green">
                        <input
                          type="checkbox"
                          checked={Boolean(form.overrideGraph)}
                          onChange={(event) => setFormField("overrideGraph", event.target.checked)}
                        />
                        <span className="slider" />
                      </span>
                    </span>
                  </label>

                  <label className="stepb-toggle-item">
                    <span className="stepb-toggle-label">Refresh Data</span>
                    <span className="stepb-toggle-control">
                      <span className="toggle-switch toggle-switch-green">
                        <input
                          type="checkbox"
                          checked={Boolean(form.refreshDataWhileBuild)}
                          onChange={async (event) => {
                            const enabled = event.target.checked;
                            setFormField("refreshDataWhileBuild", enabled);
                            const projectId = String(form.projectId ?? "").trim();
                            if (!projectId) return;
                            try {
                              await updateProjectRefreshDataWhileBuild(projectId, enabled);
                            } catch (error) {
                              addSystemLog(`Failed to save Refresh Data setting: ${String(error)}`);
                            }
                          }}
                        />
                        <span className="slider" />
                      </span>
                    </span>
                  </label>

                  <label className="stepb-toggle-item stepb-poll-seconds-item">
                    <span className="stepb-toggle-label">Auto Refresh (sec)</span>
                    <span className="stepb-toggle-control">
                      <input
                        className="stepb-poll-seconds-input"
                        type="number"
                        min="1"
                        step="1"
                        value={form.refreshDataPollSeconds}
                        placeholder="20"
                        onChange={(event) => {
                          const raw = String(event.target.value ?? "").trim();
                          if (!raw) {
                            setFormField("refreshDataPollSeconds", "");
                            return;
                          }
                          const parsed = Number(raw);
                          if (!Number.isFinite(parsed)) return;
                          setFormField("refreshDataPollSeconds", Math.max(1, Math.floor(parsed)));
                        }}
                      />
                    </span>
                  </label>
                </div>

                {canShowRuntimeControls && (
                  <section className="runtime-controls">
                    <div className="runtime-controls-head">
                      <span className="runtime-controls-title">Runtime Controls</span>
                      <label className="runtime-controls-head-toggle">
                        <span className="runtime-controls-switch-label">Show</span>
                        <span className="toggle-switch toggle-switch-green">
                          <input
                            type="checkbox"
                            checked={showRuntimeControls}
                            onChange={(event) => setShowRuntimeControls(event.target.checked)}
                          />
                          <span className="slider" />
                        </span>
                      </label>
                    </div>
                    {showRuntimeControls && (
                      <div className="runtime-controls-body runtime-controls-columns">
                        <div className="runtime-controls-column">
                          <label className="stepb-toggle-item">
                            <span className="stepb-toggle-label">OTel Tracing</span>
                            <span className="stepb-toggle-control">
                              <span className="toggle-switch toggle-switch-green">
                                <input
                                  type="checkbox"
                                  checked={Boolean(form.enableOtelTracing)}
                                  onChange={(event) => setFormField("enableOtelTracing", event.target.checked)}
                                />
                                <span className="slider" />
                              </span>
                            </span>
                          </label>
                        </div>

                        {isOracleBackend && (
                          <div className="runtime-controls-column runtime-controls-oracle">
                            <label className="stepb-toggle-item">
                              <span className="stepb-toggle-label">Oracle Runtime Overrides</span>
                              <span className="stepb-toggle-control">
                                <span className="toggle-switch toggle-switch-green">
                                  <input
                                    type="checkbox"
                                    checked={enableOracleRuntimeOverrides}
                                    onChange={(event) =>
                                      setFormField("enableOracleRuntimeOverrides", event.target.checked)
                                    }
                                  />
                                  <span className="slider" />
                                </span>
                              </span>
                            </label>
                            {enableOracleRuntimeOverrides ? (
                              <div className="field-row-two runtime-controls-grid">
                                <label className="field">
                                  <span>Oracle Pool Min</span>
                                  <input
                                    type="number"
                                    min="1"
                                    step="1"
                                    value={form.oraclePoolMin}
                                    onChange={(event) =>
                                      updateOracleRuntimeField("oraclePoolMin", event.target.value)
                                    }
                                    placeholder="2"
                                  />
                                </label>
                                <label className="field">
                                  <span>Oracle Pool Max</span>
                                  <input
                                    type="number"
                                    min="1"
                                    step="1"
                                    value={form.oraclePoolMax}
                                    onChange={(event) =>
                                      updateOracleRuntimeField("oraclePoolMax", event.target.value)
                                    }
                                    placeholder="32"
                                  />
                                </label>
                                <label className="field">
                                  <span>Oracle Pool Increment</span>
                                  <input
                                    type="number"
                                    min="1"
                                    step="1"
                                    value={form.oraclePoolIncrement}
                                    onChange={(event) =>
                                      updateOracleRuntimeField("oraclePoolIncrement", event.target.value)
                                    }
                                    placeholder="2"
                                  />
                                </label>
                                <label className="field">
                                  <span>Oracle Max Coroutines</span>
                                  <input
                                    type="number"
                                    min="1"
                                    step="1"
                                    value={form.oracleMaxCoroutines}
                                    onChange={(event) =>
                                      updateOracleRuntimeField("oracleMaxCoroutines", event.target.value)
                                    }
                                    placeholder="20"
                                  />
                                </label>
                              </div>
                            ) : (
                              <p className="field-note">
                                Oracle runtime overrides are disabled. Step B uses backend global settings.
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </section>
                )}

                <div className="step-primary-actions stepb-primary-actions">
                  <button
                    className="action-btn"
                    type="button"
                    onClick={runGraphBuild}
                    disabled={!canRunGraphBuild}
                  >
                    {graphTask.status === "running" ? "Building..." : "Run Graph Build"}
                  </button>
                  {canShowResumeGraphBuild && (
                    <button className="action-btn" type="button" onClick={runGraphBuild}>
                      {`Resume[${resumeNextBatch}/${resumeTotalBatches}]`}
                    </button>
                  )}
                  {isGraphTaskRunning && (
                    <button className="ontology-editor-cancel-btn" type="button" onClick={cancelGraphBuild}>
                      Cancel
                    </button>
                  )}
                </div>

                <div className="progress-wrap">
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${graphTask.progress}%` }} />
                  </div>
                  <span>{graphTask.progress}%</span>
                </div>

                <p className="status-line">{graphStatusLineText}</p>
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

      <PromptLabelEditorModal
        promptLabelEditor={promptLabelEditor}
        editingPromptLabelMeta={editingPromptLabelMeta}
        activeTopPromptLabelEditorTab={activeTopPromptLabelEditorTab}
        activePromptLabelEditorTab={activePromptLabelEditorTab}
        activeNodeEdgesEditorTab={activeNodeEdgesEditorTab}
        isPromptTemplateTab={isPromptTemplateTab}
        promptLabelEditorTabItems={PROMPT_LABEL_EDITOR_TAB_ITEMS}
        nodeEdgesEditorTabItems={NODE_EDGES_EDITOR_TAB_ITEMS}
        canGenerateFromLlm={canGenerateFromLlm}
        generateFromLlmHelpText={generateFromLlmHelpText}
        onClose={closePromptLabelEditor}
        onLabelNameChange={(value) =>
          setPromptLabelEditor((current) => ({
            ...current,
            labelName: String(value ?? ""),
            error: "",
            notice: "",
          }))
        }
        onTabChange={setPromptLabelEditorTab}
        onNodeEdgesTabChange={setNodeEdgesEditorTab}
        onPromptTemplateDraftChange={updatePromptTemplateDraft}
        onPromptTemplateHeightChange={updatePromptTemplateHeight}
        onPromptTemplatePreviewToggle={togglePromptTemplatePreview}
        onUpdatePromptTemplate={updateActivePromptTemplate}
        canUpdatePromptTemplate={canUpdateActivePromptTemplate}
        isUpdatingPromptTemplate={isUpdatingActivePromptTemplate}
        onTypeListChange={updatePromptLabelTypeListDraft}
        onToggleTypeSectionCollapse={togglePromptLabelTypeSectionCollapse}
        onRevertToDefault={revertPromptLabelEditorToDefault}
        onSyncFromDefault={syncPromptLabelContent}
        onGenerateFromLlm={generatePromptLabelContentFromLlm}
        onKeepRemainingOnGenerateChange={(enabled) =>
          setPromptLabelEditor((current) => ({
            ...current,
            keepRemainingOnGenerate: Boolean(enabled),
          }))
        }
        onSave={savePromptLabelTypeLists}
      />

      {ontologyEditorOpen && (
        <div className="ontology-editor-overlay">
          <article
            className="ontology-editor-panel"
            role="dialog"
            aria-modal="true"
            aria-label={
              isEntityTab
                ? "Edit ontology types, entity types tab"
                : "Edit ontology types, relationship types tab"
            }
          >
            <div className="ontology-editor-head">
              <h3>Edit ontology types</h3>
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
            <div className="ontology-editor-tabs" role="tablist" aria-label="Ontology type lists">
              <button
                type="button"
                role="tab"
                aria-selected={isEntityTab}
                className={`ontology-editor-tab ${isEntityTab ? "active" : ""}`}
                onClick={() => {
                  setOntologyEditorTab("entity");
                  setOntologyEditorRemoveMode({ entity: false, relationship: false });
                }}
              >
                Entity Types
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={!isEntityTab}
                className={`ontology-editor-tab ${!isEntityTab ? "active" : ""}`}
                onClick={() => {
                  setOntologyEditorTab("relationship");
                  setOntologyEditorRemoveMode({ entity: false, relationship: false });
                }}
              >
                Relationship Types
              </button>
            </div>
            <p className="ontology-editor-note">
              {isEntityTab
                ? ontologyGeneratedDiff.entity
                  ? "Top row is Original and editable. Bottom row is editable New/Generated. Highlighted chips changed from original."
                  : "Single editable row because no generated diff is pending."
                : ontologyGeneratedDiff.relationship
                  ? "Top row is Original and editable. Bottom row is editable New/Generated. Highlighted chips changed from original."
                  : "Single editable row because no generated diff is pending."}
            </p>
            <div className="ontology-editor-section-list">
              {isEntityTab ? (
                ontologyGeneratedDiff.entity ? (
                  <>
                    <TypeTagEditor
                      title="Original Entity Types"
                      tags={originalEntityTypeNames}
                      onChange={handleOriginalEntityTagNamesChange}
                      onOpenProperties={(index) => openTypePropertyEditor("entity", index, "original")}
                      placeholder="Add entity type and press Enter"
                      highlighted
                      changedTagNames={changedEntityTypeNames}
                    />
                    <TypeTagEditor
                      title="New / Generated Entity Types"
                      tags={draftEntityTypeNames}
                      onChange={handleEntityTagNamesChange}
                      onOpenProperties={(index) => openTypePropertyEditor("entity", index, "draft")}
                      placeholder="Add entity type and press Enter"
                      autoFocus
                      highlighted
                      removeMode={ontologyEditorRemoveMode.entity}
                      onToggleRemoveMode={() =>
                        setOntologyEditorRemoveMode((m) => ({ ...m, entity: !m.entity }))
                      }
                      selectedIndexes={ontologyMergeSelection.entity}
                      onToggleSelect={(index) => toggleOntologyTypeSelection("entity", index)}
                      onMergeSelected={() => mergeSelectedDraftTypes("entity")}
                      changedTagNames={changedEntityTypeNames}
                    />
                  </>
                ) : (
                  <TypeTagEditor
                    title="Entity Types"
                    tags={draftEntityTypeNames}
                    onChange={handleEntityTagNamesChange}
                    onOpenProperties={(index) => openTypePropertyEditor("entity", index, "draft")}
                    placeholder="Add entity type and press Enter"
                    autoFocus
                    highlighted
                    removeMode={ontologyEditorRemoveMode.entity}
                    onToggleRemoveMode={() =>
                      setOntologyEditorRemoveMode((m) => ({ ...m, entity: !m.entity }))
                    }
                    selectedIndexes={ontologyMergeSelection.entity}
                    onToggleSelect={(index) => toggleOntologyTypeSelection("entity", index)}
                    onMergeSelected={() => mergeSelectedDraftTypes("entity")}
                  />
                )
              ) : (
                ontologyGeneratedDiff.relationship ? (
                  <>
                    <TypeTagEditor
                      title="Original Relationship Types"
                      tags={originalEdgeTypeNames}
                      onChange={handleOriginalRelationshipTagNamesChange}
                      onOpenProperties={(index) =>
                        openTypePropertyEditor("relationship", index, "original")
                      }
                      placeholder="Add relationship type and press Enter"
                      highlighted
                      changedTagNames={changedEdgeTypeNames}
                    />
                    <TypeTagEditor
                      title="New / Generated Relationship Types"
                      tags={draftEdgeTypeNames}
                      onChange={handleRelationshipTagNamesChange}
                      onOpenProperties={(index) => openTypePropertyEditor("relationship", index, "draft")}
                      placeholder="Add relationship type and press Enter"
                      autoFocus
                      highlighted
                      removeMode={ontologyEditorRemoveMode.relationship}
                      onToggleRemoveMode={() =>
                        setOntologyEditorRemoveMode((m) => ({ ...m, relationship: !m.relationship }))
                      }
                      selectedIndexes={ontologyMergeSelection.relationship}
                      onToggleSelect={(index) => toggleOntologyTypeSelection("relationship", index)}
                      onMergeSelected={() => mergeSelectedDraftTypes("relationship")}
                      changedTagNames={changedEdgeTypeNames}
                    />
                  </>
                ) : (
                  <TypeTagEditor
                    title="Relationship Types"
                    tags={draftEdgeTypeNames}
                    onChange={handleRelationshipTagNamesChange}
                    onOpenProperties={(index) => openTypePropertyEditor("relationship", index, "draft")}
                    placeholder="Add relationship type and press Enter"
                    autoFocus
                    highlighted
                    removeMode={ontologyEditorRemoveMode.relationship}
                    onToggleRemoveMode={() =>
                      setOntologyEditorRemoveMode((m) => ({ ...m, relationship: !m.relationship }))
                    }
                    selectedIndexes={ontologyMergeSelection.relationship}
                    onToggleSelect={(index) => toggleOntologyTypeSelection("relationship", index)}
                    onMergeSelected={() => mergeSelectedDraftTypes("relationship")}
                  />
                )
              )}
            </div>
            {ontologyMergeRequired && hasOntologyGeneratedDiff && (
              <p className="ontology-editor-note ontology-editor-merge-warning">
                Generated ontology differs from current ontology. Click Merge Matching before Confirm.
              </p>
            )}
            {ontologyVersions.length > 0 && (
              <p className="ontology-editor-note">
                Loaded {ontologyVersions.length} ontology version{ontologyVersions.length > 1 ? "s" : ""} for
                comparison.
              </p>
            )}
            {ontologyEditorError && <p className="ontology-editor-error">{ontologyEditorError}</p>}
            <div className="ontology-editor-actions">
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={revertOntologyEditorDraft}
                disabled={savingOntologyTypes}
              >
                Revert
              </button>
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={mergeMatchingTypesFromOriginal}
                disabled={savingOntologyTypes}
              >
                Merge Matching
              </button>
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={closeOntologyEditor}
                disabled={savingOntologyTypes}
              >
                Cancel
              </button>
              <button
                className="action-btn"
                type="button"
                onClick={confirmOntologyEditor}
                disabled={!canConfirmOntologyEditor}
              >
                {savingOntologyTypes ? "Saving..." : "Confirm"}
              </button>
            </div>
          </article>
        </div>
      )}

      {isTypePropertyEditorOpen && (
        <div className="ontology-property-overlay">
          <article
            className="ontology-property-panel"
            role="dialog"
            aria-modal="true"
            aria-label={typePropertyModeLabel}
          >
            <div className="ontology-property-head">
              <button className="ontology-tag-back-btn" type="button" onClick={closeTypePropertyEditor}>
                ← Back
              </button>
              <h3>{typePropertyModeLabel}</h3>
              <button
                className="ontology-editor-close"
                type="button"
                onClick={closeTypePropertyEditor}
                aria-label="Close type property editor"
              >
                ×
              </button>
            </div>
            <p className="ontology-editor-note">{typePropertyDescription}</p>
            <div className="ontology-property-body">
              <div className="ontology-property-row ontology-inline-field">
                <span className="ontology-property-row-label">Type Name:</span>
                <div className="ontology-property-row-editor">
                  <input
                    value={String(typePropertyDraft.name ?? "")}
                    onChange={(event) => updateTypePropertyDraftField("name", event.target.value)}
                    placeholder="Type name"
                  />
                </div>
              </div>

              <div className="ontology-property-row align-top">
                <span className="ontology-property-row-label">Description:</span>
                <div className="ontology-property-row-editor">
                  <textarea
                    value={String(typePropertyDraft.description ?? "")}
                    onChange={(event) => updateTypePropertyDraftField("description", event.target.value)}
                    rows={3}
                    placeholder="Type description"
                  />
                </div>
              </div>

              {typePropertyEditor.mode === "entity" && (
                <div className="ontology-property-row align-top">
                  <span className="ontology-property-row-label">Metadata (String List):</span>
                  <div className="ontology-property-row-editor">
                    <EditableStringListEditor
                      values={Array.isArray(typePropertyDraft.examples) ? typePropertyDraft.examples : []}
                      onChange={(nextValues) => updateTypePropertyDraftField("examples", nextValues)}
                      placeholder="Add metadata item and press Enter"
                    />
                  </div>
                </div>
              )}

              <div className="ontology-property-row align-top">
                <span className="ontology-property-row-label">Attributes (JSON List):</span>
                <div className="ontology-property-row-editor">
                  <JsonListEditor
                    values={
                      Array.isArray(typePropertyEditor.jsonTexts?.attributes)
                        ? typePropertyEditor.jsonTexts.attributes
                        : []
                    }
                    onChange={(nextValues) => updateTypePropertyJsonField("attributes", nextValues)}
                    invalidIndexes={typePropertyEditor.invalidJsonIndexes?.attributes ?? []}
                    addLabel="Add attribute JSON"
                  />
                </div>
              </div>

              {typePropertyEditor.mode === "relationship" && (
                <div className="ontology-property-row align-top">
                  <span className="ontology-property-row-label">Source Targets:</span>
                  <div className="ontology-property-row-editor">
                    <div className="ontology-source-target-list">
                      {(Array.isArray(typePropertyEditor.jsonTexts?.source_targets)
                        ? typePropertyEditor.jsonTexts.source_targets
                        : []
                      ).map((rowValue, index) => {
                        const row = normalizeSourceTargetRowValue(rowValue);
                        const invalidSet = new Set(
                          Array.isArray(typePropertyEditor.invalidJsonIndexes?.source_targets)
                            ? typePropertyEditor.invalidJsonIndexes.source_targets
                            : [],
                        );
                        const invalid = invalidSet.has(index);
                        return (
                          <div
                            className={`ontology-source-target-row ${invalid ? "invalid" : ""}`}
                            key={`source-target-${index}`}
                          >
                            <span className="ontology-source-target-inline-label">Source</span>
                            <input
                              value={row.source}
                              onChange={(event) =>
                                updateSourceTargetRow(index, "source", event.target.value)
                              }
                              placeholder="Source type"
                            />
                            <span className="ontology-source-target-inline-label">Target</span>
                            <input
                              value={row.target}
                              onChange={(event) =>
                                updateSourceTargetRow(index, "target", event.target.value)
                              }
                              placeholder="Target type"
                            />
                            <button
                              className="ontology-source-target-remove-btn"
                              type="button"
                              onClick={() => removeSourceTargetRow(index)}
                              aria-label={`Remove source-target pair ${index + 1}`}
                              title="Remove source-target pair"
                            >
                              ×
                            </button>
                          </div>
                        );
                      })}
                    </div>
                    <button className="ontology-json-add-btn" type="button" onClick={addSourceTargetRow}>
                      Add source-target
                    </button>
                  </div>
                </div>
              )}
            </div>
            {typePropertyEditor.error && <p className="ontology-editor-error">{typePropertyEditor.error}</p>}
            <div className="ontology-editor-actions">
              <button
                className="ontology-editor-delete-btn"
                type="button"
                onClick={deleteTypePropertyEditor}
              >
                Delete Type
              </button>
              <button className="ontology-editor-cancel-btn" type="button" onClick={closeTypePropertyEditor}>
                Cancel
              </button>
              <button className="action-btn" type="button" onClick={confirmTypePropertyEditor}>
                Confirm
              </button>
            </div>
          </article>
        </div>
      )}
    </section>
  );
}
