import { BACKEND_DISPLAY_URL } from "../TaskStore/constants";

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

const buildAbsoluteApiUrl = (path) => {
  const normalizedBase = String(BACKEND_DISPLAY_URL ?? "").trim().replace(/\/$/, "");
  const normalizedPath = `/${String(path ?? "").trim().replace(/^\/+/, "")}`;
  if (!normalizedBase) return normalizedPath;
  return `${normalizedBase}${normalizedPath}`;
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

export {
  PROMPT_LABEL_FIELD_PAIR_MAP,
  PROMPT_LABEL_TYPE_FIELDS,
  buildAbsoluteApiUrl,
  clonePlainData,
  createEmptyPromptLabelTypeLists,
  createPromptLabelTypeCollapseState,
  extractOntologyTypeDrafts,
  normalizePromptLabelTypeListValues,
  normalizePromptLabelTypeListsPayload,
  normalizeStringList,
  normalizeTypeKey,
  normalizeTypeTag,
  remapTypeDefinitions,
  removeCrossListDuplicates,
  sanitizeEntityTypeDraft,
  sanitizeRelationshipTypeDraft,
};
