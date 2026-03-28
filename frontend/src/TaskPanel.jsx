import { useEffect, useRef, useState } from "react";

import EditableStringListEditor from "./components/EditableStringListEditor";
import TagChip from "./components/TagChip";
import { useTaskStore } from "./TaskStore/index";

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

const normalizeTypeKey = (value) => normalizeTypeTag(value).toLowerCase();

const clonePlainData = (value) => JSON.parse(JSON.stringify(value ?? {}));

const normalizeStringList = (values) => {
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

const createDefaultEntityType = (name) => ({
  name: normalizeTypeTag(name),
  description: name ? `A ${name} entity.` : "",
  attributes: [],
  examples: [],
});

const createDefaultRelationshipType = (name) => ({
  name: normalizeTypeTag(name),
  description: name ? `A ${name} relationship.` : "",
  attributes: [],
  source_targets: [],
});

const sanitizeEntityTypeDraft = (raw) => {
  const name = normalizeTypeTag(raw?.name);
  if (!name) return null;
  return {
    ...raw,
    name,
    description: String(raw?.description ?? ""),
    attributes: Array.isArray(raw?.attributes) ? raw.attributes : [],
    examples: normalizeStringList(raw?.examples),
  };
};

const sanitizeRelationshipTypeDraft = (raw) => {
  const name = normalizeTypeTag(raw?.name);
  if (!name) return null;
  return {
    ...raw,
    name,
    description: String(raw?.description ?? ""),
    attributes: Array.isArray(raw?.attributes) ? raw.attributes : [],
    source_targets: Array.isArray(raw?.source_targets) ? raw.source_targets : [],
  };
};

const extractOntologyTypeDrafts = (project, key, mode) => {
  const items = Array.isArray(project?.ontology?.[key]) ? project.ontology[key] : [];
  const seen = new Set();
  const result = [];

  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const normalizedName = normalizeTypeTag(item?.name);
    if (!normalizedName) continue;
    const dedupeKey = normalizedName.toLowerCase();
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);

    if (mode === "entity") {
      const draft = sanitizeEntityTypeDraft(item);
      if (draft) result.push(draft);
    } else {
      const draft = sanitizeRelationshipTypeDraft(item);
      if (draft) result.push(draft);
    }
  }

  return result;
};

const normalizeDraftTypeNames = (values) => {
  const nextNames = [];
  const seen = new Set();
  for (const value of Array.isArray(values) ? values : []) {
    const normalized = normalizeTypeTag(value);
    if (!normalized) continue;
    const dedupeKey = normalized.toLowerCase();
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    nextNames.push(normalized);
  }
  return nextNames;
};

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

const normalizePromptLabelTypeListsPayload = (value) => ({
  individual: normalizePromptLabelTypeListValues(value?.individual),
  individual_exception: normalizePromptLabelTypeListValues(value?.individual_exception),
  organization: normalizePromptLabelTypeListValues(value?.organization),
  organization_exception: normalizePromptLabelTypeListValues(value?.organization_exception),
  relationship: normalizePromptLabelTypeListValues(value?.relationship),
  relationship_exception: normalizePromptLabelTypeListValues(value?.relationship_exception),
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

const pickDraftDefinitionByName = (definitionsByName, usedIndexes, name) => {
  const candidates = definitionsByName.get(normalizeTypeKey(name)) ?? [];
  for (const candidate of candidates) {
    if (usedIndexes.has(candidate.index)) continue;
    usedIndexes.add(candidate.index);
    return candidate;
  }
  return null;
};

const pickDraftDefinitionByIndex = (definitions, usedIndexes, index) => {
  if (index >= 0 && index < definitions.length && !usedIndexes.has(index)) {
    usedIndexes.add(index);
    return { definition: definitions[index], index };
  }
  for (let cursor = 0; cursor < definitions.length; cursor += 1) {
    if (usedIndexes.has(cursor)) continue;
    usedIndexes.add(cursor);
    return { definition: definitions[cursor], index: cursor };
  }
  return null;
};

const remapTypeDefinitions = (existingDefinitions, nextNames, mode) => {
  const definitions = Array.isArray(existingDefinitions) ? existingDefinitions : [];
  const normalizedNames = normalizeDraftTypeNames(nextNames);
  const definitionsByName = new Map();

  definitions.forEach((definition, index) => {
    const key = normalizeTypeKey(definition?.name);
    if (!key) return;
    const bucket = definitionsByName.get(key) ?? [];
    bucket.push({ definition, index });
    definitionsByName.set(key, bucket);
  });

  const usedIndexes = new Set();
  return normalizedNames
    .map((name, index) => {
      const source =
        pickDraftDefinitionByName(definitionsByName, usedIndexes, name) ??
        pickDraftDefinitionByIndex(definitions, usedIndexes, index);
      const definition = source?.definition
        ? { ...source.definition, name }
        : mode === "entity"
          ? createDefaultEntityType(name)
          : createDefaultRelationshipType(name);
      return mode === "entity"
        ? sanitizeEntityTypeDraft(definition)
        : sanitizeRelationshipTypeDraft(definition);
    })
    .filter(Boolean);
};

function TypeTagEditor({ title, tags, onChange, onOpenProperties, placeholder, autoFocus = false, highlighted = false }) {
  const [inputValue, setInputValue] = useState("");
  const addInputRef = useRef(null);

  useEffect(() => {
    if (!autoFocus) return;
    addInputRef.current?.focus();
  }, [autoFocus]);

  const hasDuplicate = (nextValue) =>
    tags.some((tag) => normalizeTypeTag(tag).toLowerCase() === normalizeTypeTag(nextValue).toLowerCase());

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

  return (
    <section className={`ontology-editor-section ${highlighted ? "focused" : ""}`}>
      <h4>{title}</h4>
      <div className="ontology-tag-editor-box" onClick={() => addInputRef.current?.focus()}>
        {tags.map((tag, index) => (
          <TagChip
            key={`${tag}-${index}`}
            label={tag}
            mainButtonClassName="ontology-tag-chip"
            onClick={(event) => {
              event.stopPropagation();
              onOpenProperties(index);
            }}
          />
        ))}
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
        Click a tag to edit full properties. Press Backspace on empty input to remove the last tag.
      </p>
    </section>
  );
}

function JsonListEditor({ values = [], onChange, invalidIndexes = [], addLabel }) {
  const invalidSet = new Set(Array.isArray(invalidIndexes) ? invalidIndexes : []);

  const updateItem = (index, nextValue) => {
    const nextValues = [...values];
    nextValues[index] = nextValue;
    onChange(nextValues);
  };

  const removeItem = (index) => {
    onChange(values.filter((_, cursor) => cursor !== index));
  };

  const appendItem = () => {
    onChange([...(Array.isArray(values) ? values : []), "{}"]);
  };

  return (
    <div>
      <div className="ontology-json-list">
        {(Array.isArray(values) ? values : []).map((value, index) => (
          <div className="ontology-json-item" key={`${addLabel}-${index}`}>
            <textarea
              className={`ontology-json-item-input ${invalidSet.has(index) ? "invalid" : ""}`}
              value={String(value ?? "")}
              rows={3}
              onChange={(event) => updateItem(index, event.target.value)}
            />
            <div className="ontology-json-item-actions">
              <button
                className="ontology-json-remove-btn"
                type="button"
                onClick={() => removeItem(index)}
              >
                Remove
              </button>
            </div>
            {invalidSet.has(index) && (
              <p className="ontology-json-item-error">Invalid JSON. Fix this item before confirming.</p>
            )}
          </div>
        ))}
      </div>
      <button className="ontology-json-add-btn" type="button" onClick={appendItem}>
        {addLabel}
      </button>
    </div>
  );
}

export default function TaskPanel() {
  const {
    state,
    setViewMode,
    setFormField,
    setProjectPromptLabel,
    createPromptLabel,
    fetchPromptLabels,
    syncPromptLabelFromLangfuse,
    getPromptLabelTypeLists,
    updatePromptLabelTypeLists,
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
  const promptLabelDropdownRef = useRef(null);
  const [activeStepTab, setActiveStepTab] = useState("A");
  const [activeBackendTab, setActiveBackendTab] = useState("build");
  const [ontologyEditorMode, setOntologyEditorMode] = useState("");
  const [draftEntityTypes, setDraftEntityTypes] = useState([]);
  const [draftEdgeTypes, setDraftEdgeTypes] = useState([]);
  const [typePropertyEditor, setTypePropertyEditor] = useState({
    open: false,
    mode: "",
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
    loadingTypes: false,
    savingTypes: false,
    typeLists: createEmptyPromptLabelTypeLists(),
    collapsedTypeSections: createPromptLabelTypeCollapseState(),
    syncing: false,
    notice: "",
    error: "",
  });
  const [promptLabelDropdownOpen, setPromptLabelDropdownOpen] = useState(false);

  const stepBUnlocked =
    ontologyTask.status === "success" || graphTask.status === "running" || graphTask.status === "success";
  const isProjectCreated = Boolean(form.projectId);
  const canOpenOntologyEditor = Boolean(form.projectId) && ontologyTask.status !== "running";
  const isEntityEditor = ontologyEditorMode === "entity";
  const draftEntityTypeNames = draftEntityTypes.map((item) => normalizeTypeTag(item?.name)).filter(Boolean);
  const draftEdgeTypeNames = draftEdgeTypes.map((item) => normalizeTypeTag(item?.name)).filter(Boolean);
  const isTypePropertyEditorOpen = Boolean(typePropertyEditor.open);
  const promptLabelItems =
    promptLabelCatalog.items.length > 0
      ? promptLabelCatalog.items
      : [{ name: form.promptLabel || "Production" }];

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
      loadingTypes: true,
      savingTypes: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      collapsedTypeSections: createPromptLabelTypeCollapseState(),
      syncing: false,
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
      loadingTypes: false,
      savingTypes: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      collapsedTypeSections: createPromptLabelTypeCollapseState(),
      syncing: false,
      notice: "",
      error: "",
    });
  };

  const closePromptLabelEditor = () => {
    if (promptLabelEditor.syncing || promptLabelEditor.savingTypes) return;
    setPromptLabelEditor({
      open: false,
      labelName: "",
      isNewLabel: false,
      loadingTypes: false,
      savingTypes: false,
      typeLists: createEmptyPromptLabelTypeLists(),
      collapsedTypeSections: createPromptLabelTypeCollapseState(),
      syncing: false,
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

  const syncPromptLabelContent = async () => {
    if (promptLabelEditor.isNewLabel) {
      setPromptLabelEditor((current) => ({
        ...current,
        error: "Sync is available after the new label is created.",
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

    setPromptLabelEditor((current) => ({
      ...current,
      syncing: true,
      error: "",
      notice: "",
    }));
    try {
      const syncResult = await syncPromptLabelFromLangfuse(labelName);
      const typeResult = await getPromptLabelTypeLists(labelName);
      await fetchPromptLabels({ syncFormLabel: false });
      const downloadedFiles = Number(syncResult?.downloaded_files ?? 0);
      setPromptLabelEditor((current) => ({
        ...current,
        syncing: false,
        loadingTypes: false,
        typeLists: normalizePromptLabelTypeListsPayload(typeResult?.types),
        error: "",
        notice: `Synced '${labelName}' from default (${downloadedFiles} file${downloadedFiles === 1 ? "" : "s"}).`,
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

    const existingLabels = new Set(
      promptLabelItems
        .map((item) => String(item?.name ?? "").trim().toLowerCase())
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

    const payload = normalizePromptLabelTypeListsPayload(promptLabelEditor.typeLists);
    const hasCustomTypeListData = PROMPT_LABEL_TYPE_FIELDS.some(
      (field) => Array.isArray(payload[field]) && payload[field].length > 0,
    );

    setPromptLabelEditor((current) => ({
      ...current,
      savingTypes: true,
      error: "",
      notice: "",
    }));
    try {
      let payloadToSave = payload;

      if (promptLabelEditor.isNewLabel) {
        await createPromptLabel(labelName);
        if (!hasCustomTypeListData) {
          const productionTypes = await getPromptLabelTypeLists("Production");
          payloadToSave = normalizePromptLabelTypeListsPayload(productionTypes?.types);
        }
      }

      const result = await updatePromptLabelTypeLists(labelName, payloadToSave);
      await fetchPromptLabels({ syncFormLabel: false });
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
        loadingTypes: false,
        savingTypes: false,
        typeLists: createEmptyPromptLabelTypeLists(),
        collapsedTypeSections: createPromptLabelTypeCollapseState(),
        syncing: false,
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
    if (promptLabelEditor.syncing || promptLabelEditor.savingTypes) return;

    setPromptLabelEditor((current) => ({
      ...current,
      loadingTypes: true,
      error: "",
      notice: "",
    }));
    try {
      const defaultTypeLists = await getPromptLabelTypeLists("Production");
      setPromptLabelEditor((current) => ({
        ...current,
        loadingTypes: false,
        typeLists: normalizePromptLabelTypeListsPayload(defaultTypeLists?.types),
        error: "",
        notice: "Reverted to Production defaults. Save to apply changes.",
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

  const closeTypePropertyEditor = () => {
    setTypePropertyEditor({
      open: false,
      mode: "",
      index: -1,
      draft: null,
      jsonTexts: {},
      invalidJsonIndexes: {},
      error: "",
    });
  };

  const openTypePropertyEditor = (mode, index) => {
    const sourceDefinitions = mode === "entity" ? draftEntityTypes : draftEdgeTypes;
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
      typePropertyEditor.mode === "entity" ? draftEntityTypes : draftEdgeTypes;
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
      setDraftEntityTypes((current) =>
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
      setDraftEntityTypes((current) => current.filter((_, index) => index !== targetIndex));
    } else if (typePropertyEditor.mode === "relationship") {
      setDraftEdgeTypes((current) => current.filter((_, index) => index !== targetIndex));
    }
    closeTypePropertyEditor();
  };

  const openOntologyEditor = (mode) => {
    if (!canOpenOntologyEditor) {
      addSystemLog("Ontology editor is available after Step A finishes.");
      return;
    }
    setOntologyEditorMode(mode);
    setDraftEntityTypes(extractOntologyTypeDrafts(currentProject, "entity_types", "entity"));
    setDraftEdgeTypes(extractOntologyTypeDrafts(currentProject, "edge_types", "relationship"));
    setOntologyEditorError("");
    closeTypePropertyEditor();
  };

  const closeOntologyEditor = () => {
    if (savingOntologyTypes) return;
    setOntologyEditorMode("");
    setOntologyEditorError("");
    closeTypePropertyEditor();
  };

  const revertOntologyEditorDraft = () => {
    if (!Boolean(ontologyEditorMode) || savingOntologyTypes) return;
    setDraftEntityTypes(extractOntologyTypeDrafts(currentProject, "entity_types", "entity"));
    setDraftEdgeTypes(extractOntologyTypeDrafts(currentProject, "edge_types", "relationship"));
    setOntologyEditorError("");
    closeTypePropertyEditor();
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
        entityTypes: draftEntityTypes,
        edgeTypes: draftEdgeTypes,
      });
      setOntologyEditorMode("");
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
  };

  const handleRelationshipTagNamesChange = (nextNames) => {
    setDraftEdgeTypes((current) => remapTypeDefinitions(current, nextNames, "relationship"));
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

    getPromptLabelTypeLists(labelName)
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
            typeLists: normalizePromptLabelTypeListsPayload(result?.types),
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
    if (!isTypePropertyEditorOpen && !promptLabelEditor.open && !Boolean(ontologyEditorMode)) {
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
      if (ontologyEditorMode) {
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
    ontologyEditorMode,
    savingOntologyTypes,
  ]);

  useEffect(() => {
    if (!logContainerRef.current) return;
    logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
  }, [systemLogs.length, activeBackendTab]);

  useEffect(() => {
    if (activeStepTab === "B" && !stepBUnlocked) {
      setActiveStepTab("A");
    }
  }, [activeStepTab, stepBUnlocked]);

  const typePropertyDraft = typePropertyEditor.draft ?? {};
  const typePropertyModeLabel =
    typePropertyEditor.mode === "entity" ? "Entity Type Properties" : "Relationship Type Properties";
  const typePropertyDescription =
    typePropertyEditor.mode === "entity"
      ? "Edit name, description, metadata string list, and attribute JSON payloads."
      : "Edit name, description, attribute JSON payloads, and source-target JSON payloads.";
  const editingPromptLabelMeta = promptLabelCatalog.items.find(
    (item) =>
      String(item?.name ?? "").trim().toLowerCase() ===
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
                    <span>Category Label</span>
                    <div className="label-dropdown" ref={promptLabelDropdownRef}>
                      <button
                        className={`label-dropdown-trigger ${promptLabelDropdownOpen ? "open" : ""}`}
                        type="button"
                        onClick={() => setPromptLabelDropdownOpen((current) => !current)}
                        aria-haspopup="listbox"
                        aria-expanded={promptLabelDropdownOpen}
                      >
                        <span>{form.promptLabel || "Production"}</span>
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
                              const isSelected =
                                String(form.promptLabel ?? "").trim().toLowerCase() ===
                                labelName.toLowerCase();
                              return (
                                <div
                                  className={`label-dropdown-item ${isSelected ? "selected" : ""}`}
                                  key={labelName}
                                  role="option"
                                  aria-selected={isSelected}
                                >
                                  <button
                                    className="label-dropdown-item-main"
                                    type="button"
                                    onClick={() => {
                                      setProjectPromptLabel(labelName);
                                      setPromptLabelDropdownOpen(false);
                                    }}
                                    title={labelName}
                                  >
                                    <span className="label-dropdown-item-name">{labelName}</span>
                                    {isSelected && (
                                      <span className="label-dropdown-item-selected">Selected</span>
                                    )}
                                  </button>
                                  <button
                                    className="label-dropdown-item-edit"
                                    type="button"
                                    onClick={() => openPromptLabelEditor(labelName)}
                                    aria-label={`Edit label ${labelName}`}
                                    title={`Edit label ${labelName}`}
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
                disabled={promptLabelEditor.syncing || promptLabelEditor.savingTypes}
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
                ? "Create a new category label. Nothing is saved until you click Create Label."
                : "Edit list values for this label. Sync From Default refreshes templates from Langfuse defaults."}
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

              {promptLabelEditor.loadingTypes && (
                <p className="field-note">Loading label types...</p>
              )}

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
                  promptLabelEditor.loadingTypes ||
                  promptLabelEditor.syncing ||
                  promptLabelEditor.savingTypes;
                const isCollapsed = Boolean(promptLabelEditor?.collapsedTypeSections?.[row.field]);
                return (
                  <div
                    key={row.field}
                    className={`ontology-property-row align-top has-collapse ${isCollapsed ? "collapsed" : ""}`}
                  >
                    <span className="ontology-property-row-label">
                      <span
                        className={`ontology-property-row-collapse-indicator ${isCollapsed ? "collapsed" : "expanded"}`}
                        aria-hidden="true"
                      >
                        {isCollapsed ? "+" : "-"}
                      </span>
                      {row.label}:
                    </span>
                    <div className="ontology-property-row-editor">
                      {isCollapsed ? (
                        <p className="field-note ontology-property-collapsed-note">Collapsed</p>
                      ) : (
                        <EditableStringListEditor
                          values={promptLabelEditor.typeLists?.[row.field] ?? []}
                          onChange={(nextValues) => updatePromptLabelTypeListDraft(row.field, nextValues)}
                          placeholder={row.placeholder}
                          disabled={disabled}
                        />
                      )}
                    </div>
                    <button
                      className="ontology-property-row-collapse-btn"
                      type="button"
                      onClick={() => togglePromptLabelTypeSectionCollapse(row.field)}
                      disabled={disabled}
                      aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${row.label}`}
                      title={isCollapsed ? "Expand section" : "Collapse section"}
                    >
                      <span aria-hidden="true" className="ontology-property-row-collapse-icon">
                        {isCollapsed ? "▶️" : "🔽"}
                      </span>
                    </button>
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
                disabled={promptLabelEditor.syncing || promptLabelEditor.savingTypes}
              >
                Cancel
              </button>
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={revertPromptLabelEditorToDefault}
                disabled={
                  promptLabelEditor.loadingTypes ||
                  promptLabelEditor.syncing ||
                  promptLabelEditor.savingTypes
                }
              >
                Revert to Default
              </button>
              <button
                className="ontology-editor-cancel-btn"
                type="button"
                onClick={syncPromptLabelContent}
                disabled={
                  promptLabelEditor.isNewLabel || promptLabelEditor.syncing || promptLabelEditor.savingTypes
                }
              >
                {promptLabelEditor.syncing ? "Syncing..." : "Sync From Default"}
              </button>
              <button
                className="action-btn"
                type="button"
                onClick={savePromptLabelTypeLists}
                disabled={
                  promptLabelEditor.loadingTypes ||
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

      {Boolean(ontologyEditorMode) && (
        <div className="ontology-editor-overlay">
          <article
            className="ontology-editor-panel"
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
                ? "Update entity type names. Use tag click to open the full property editor."
                : "Update relationship type names. Use tag click to open the full property editor."}
            </p>
            <div className="ontology-editor-section-list">
              {isEntityEditor ? (
                <TypeTagEditor
                  title="Entity Types"
                  tags={draftEntityTypeNames}
                  onChange={handleEntityTagNamesChange}
                  onOpenProperties={(index) => openTypePropertyEditor("entity", index)}
                  placeholder="Add entity type and press Enter"
                  autoFocus
                  highlighted
                />
              ) : (
                <TypeTagEditor
                  title="Relationship Types"
                  tags={draftEdgeTypeNames}
                  onChange={handleRelationshipTagNamesChange}
                  onOpenProperties={(index) => openTypePropertyEditor("relationship", index)}
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
                onClick={revertOntologyEditorDraft}
                disabled={savingOntologyTypes}
              >
                Revert
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
                disabled={savingOntologyTypes || isTypePropertyEditorOpen}
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
                  <span className="ontology-property-row-label">Source Targets (JSON List):</span>
                  <div className="ontology-property-row-editor">
                    <JsonListEditor
                      values={
                        Array.isArray(typePropertyEditor.jsonTexts?.source_targets)
                          ? typePropertyEditor.jsonTexts.source_targets
                          : []
                      }
                      onChange={(nextValues) => updateTypePropertyJsonField("source_targets", nextValues)}
                      invalidIndexes={typePropertyEditor.invalidJsonIndexes?.source_targets ?? []}
                      addLabel="Add source-target JSON"
                    />
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
