function normalizeProjectId(value) {
  return String(value ?? "").trim();
}

function normalizePositiveInteger(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function normalizeNonNegativeInteger(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function normalizePromptLabel(value) {
  const normalized = String(value ?? "").trim();
  return normalized || "Production";
}

function getPreferredPromptLabel(catalogItems, desiredLabel) {
  const normalizedDesired = normalizePromptLabel(desiredLabel);
  const labels = Array.isArray(catalogItems) ? catalogItems : [];
  if (!labels.length) return normalizedDesired || "Production";

  const getLabelName = (item) => String(item?.display_name ?? item?.name ?? "").trim();
  const normalizedDesiredLower = normalizedDesired.toLowerCase();
  const matchedDesiredLabel = labels.find((item) => {
    const displayName = getLabelName(item).toLowerCase();
    const rawName = String(item?.name ?? "").trim().toLowerCase();
    return displayName === normalizedDesiredLower || rawName === normalizedDesiredLower;
  });
  if (matchedDesiredLabel) {
    return getLabelName(matchedDesiredLabel) || normalizedDesired;
  }

  const production = labels.find(
    (item) => getLabelName(item).toLowerCase() === "production",
  );
  if (production) return getLabelName(production) || "Production";
  return getLabelName(labels[0]) || "Production";
}

async function parseJsonResponse(response, endpointLabel) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${endpointLabel} returned non-JSON response`);
  }
}

function buildGraphDataApiPath(graphId, projectWorkspaceId, options = {}) {
  const params = new URLSearchParams({ include_episode_data: "false" });
  const normalizedWorkspaceId = String(projectWorkspaceId ?? "").trim();
  if (normalizedWorkspaceId) {
    params.set("project_workspace_id", normalizedWorkspaceId);
  }
  const normalizedGraphBackend = String(options?.graphBackend ?? "").trim();
  if (normalizedGraphBackend) {
    params.set("graph_backend", normalizedGraphBackend);
  }
  const normalizedProjectId = String(options?.projectId ?? "").trim();
  if (normalizedProjectId) {
    params.set("project_id", normalizedProjectId);
  }
  return `/api/data/${encodeURIComponent(String(graphId ?? "").trim())}?${params.toString()}`;
}

function normalizeOntologyTypeName(value) {
  return String(value ?? "")
    .trim()
    .replace(/\s+/g, " ");
}

function normalizeOntologyLookupKey(value) {
  return normalizeOntologyTypeName(value).toLowerCase();
}

function normalizeOntologyTypeNames(values) {
  const normalizedNames = [];
  const seen = new Set();
  for (const value of Array.isArray(values) ? values : []) {
    const normalized = normalizeOntologyTypeName(value);
    if (!normalized) continue;
    const dedupeKey = normalized.toLowerCase();
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    normalizedNames.push(normalized);
  }
  return normalizedNames;
}

function takeDefinitionByName(definitionsByName, usedIndexes, lookupName) {
  const candidates = definitionsByName.get(normalizeOntologyLookupKey(lookupName)) ?? [];
  for (const candidate of candidates) {
    if (usedIndexes.has(candidate.index)) continue;
    usedIndexes.add(candidate.index);
    return candidate;
  }
  return null;
}

function takeDefinitionByIndex(definitions, usedIndexes, index) {
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
}

function buildUpdatedOntologyFromTypeNames(existingOntology, entityTypeNames, edgeTypeNames) {
  const baseOntology =
    existingOntology && typeof existingOntology === "object" ? existingOntology : {};
  const existingEntityTypes = Array.isArray(baseOntology.entity_types)
    ? baseOntology.entity_types
    : [];
  const existingEdgeTypes = Array.isArray(baseOntology.edge_types) ? baseOntology.edge_types : [];

  const normalizedEntityTypeNames = normalizeOntologyTypeNames(entityTypeNames);
  const normalizedEdgeTypeNames = normalizeOntologyTypeNames(edgeTypeNames);

  const entityDefinitionsByName = new Map();
  existingEntityTypes.forEach((definition, index) => {
    const key = normalizeOntologyLookupKey(definition?.name);
    if (!key) return;
    const definitions = entityDefinitionsByName.get(key) ?? [];
    definitions.push({ definition, index });
    entityDefinitionsByName.set(key, definitions);
  });

  const usedEntityIndexes = new Set();
  const entitySources = normalizedEntityTypeNames.map((name, index) => {
    return (
      takeDefinitionByName(entityDefinitionsByName, usedEntityIndexes, name) ??
      takeDefinitionByIndex(existingEntityTypes, usedEntityIndexes, index)
    );
  });

  const nextEntityTypes = normalizedEntityTypeNames.map((name, index) => {
    const source = entitySources[index];
    const existingEntity = source?.definition;
    if (existingEntity && typeof existingEntity === "object") {
      return {
        ...existingEntity,
        name,
        attributes: Array.isArray(existingEntity.attributes) ? existingEntity.attributes : [],
        examples: Array.isArray(existingEntity.examples) ? existingEntity.examples : [],
      };
    }
    return {
      name,
      description: `A ${name} entity.`,
      attributes: [],
      examples: [],
    };
  });

  const entityRenameMap = new Map();
  entitySources.forEach((source, index) => {
    const existingName = normalizeOntologyTypeName(source?.definition?.name);
    const updatedName = normalizedEntityTypeNames[index];
    if (!existingName || !updatedName || existingName === updatedName) return;
    entityRenameMap.set(existingName, updatedName);
  });

  const entityNameSet = new Set(normalizedEntityTypeNames);
  const fallbackSource = normalizedEntityTypeNames[0] || "Entity";
  const fallbackTarget = normalizedEntityTypeNames[1] || normalizedEntityTypeNames[0] || "Entity";

  const normalizeSourceOrTarget = (value, fallbackName) => {
    const normalizedName = normalizeOntologyTypeName(value);
    const renamed = entityRenameMap.get(normalizedName) ?? normalizedName;
    if (!entityNameSet.size) {
      return renamed || "Entity";
    }
    if (renamed && entityNameSet.has(renamed)) {
      return renamed;
    }
    return fallbackName;
  };

  const edgeDefinitionsByName = new Map();
  existingEdgeTypes.forEach((definition, index) => {
    const key = normalizeOntologyLookupKey(definition?.name);
    if (!key) return;
    const definitions = edgeDefinitionsByName.get(key) ?? [];
    definitions.push({ definition, index });
    edgeDefinitionsByName.set(key, definitions);
  });

  const usedEdgeIndexes = new Set();
  const edgeSources = normalizedEdgeTypeNames.map((name, index) => {
    return (
      takeDefinitionByName(edgeDefinitionsByName, usedEdgeIndexes, name) ??
      takeDefinitionByIndex(existingEdgeTypes, usedEdgeIndexes, index)
    );
  });

  const nextEdgeTypes = normalizedEdgeTypeNames.map((name, index) => {
    const source = edgeSources[index];
    const existingEdge = source?.definition;
    const edgeBase =
      existingEdge && typeof existingEdge === "object"
        ? { ...existingEdge, name }
        : {
            name,
            description: `A ${name} relationship.`,
            attributes: [],
            source_targets: [],
          };

    const sourceTargets = [];
    const rawSourceTargets = Array.isArray(edgeBase.source_targets) ? edgeBase.source_targets : [];
    for (const rawSourceTarget of rawSourceTargets) {
      if (!rawSourceTarget || typeof rawSourceTarget !== "object") continue;
      sourceTargets.push({
        source: normalizeSourceOrTarget(rawSourceTarget.source, fallbackSource),
        target: normalizeSourceOrTarget(rawSourceTarget.target, fallbackTarget),
      });
    }

    if (sourceTargets.length === 0) {
      sourceTargets.push({
        source: fallbackSource,
        target: fallbackTarget,
      });
    }

    return {
      ...edgeBase,
      name,
      attributes: Array.isArray(edgeBase.attributes) ? edgeBase.attributes : [],
      source_targets: sourceTargets,
    };
  });

  return {
    ...baseOntology,
    entity_types: nextEntityTypes,
    edge_types: nextEdgeTypes,
  };
}

function buildUpdatedOntologyFromDefinitions(
  existingOntology,
  entityTypeDefinitions = [],
  edgeTypeDefinitions = [],
) {
  const normalizedEntityDefinitions = Array.isArray(entityTypeDefinitions)
    ? entityTypeDefinitions.filter((item) => item && typeof item === "object")
    : [];
  const normalizedEdgeDefinitions = Array.isArray(edgeTypeDefinitions)
    ? edgeTypeDefinitions.filter((item) => item && typeof item === "object")
    : [];

  const entityTypeNames = normalizeOntologyTypeNames(normalizedEntityDefinitions.map((item) => item?.name));
  const edgeTypeNames = normalizeOntologyTypeNames(normalizedEdgeDefinitions.map((item) => item?.name));

  const nextOntology = buildUpdatedOntologyFromTypeNames(existingOntology, entityTypeNames, edgeTypeNames);

  const entityDefinitionByName = new Map();
  normalizedEntityDefinitions.forEach((definition) => {
    const key = normalizeOntologyLookupKey(definition?.name);
    if (!key || entityDefinitionByName.has(key)) return;
    entityDefinitionByName.set(key, definition);
  });

  const edgeDefinitionByName = new Map();
  normalizedEdgeDefinitions.forEach((definition) => {
    const key = normalizeOntologyLookupKey(definition?.name);
    if (!key || edgeDefinitionByName.has(key)) return;
    edgeDefinitionByName.set(key, definition);
  });

  const entityTypes = Array.isArray(nextOntology?.entity_types) ? nextOntology.entity_types : [];
  const edgeTypes = Array.isArray(nextOntology?.edge_types) ? nextOntology.edge_types : [];

  const mergedEntityTypes = entityTypes.map((definition) => {
    const key = normalizeOntologyLookupKey(definition?.name);
    const edited = entityDefinitionByName.get(key);
    if (!edited) return definition;
    return {
      ...definition,
      ...edited,
      name: normalizeOntologyTypeName(edited?.name) || definition?.name,
      attributes: Array.isArray(edited?.attributes) ? edited.attributes : definition?.attributes ?? [],
      examples: Array.isArray(edited?.examples) ? edited.examples : definition?.examples ?? [],
    };
  });

  const mergedEdgeTypes = edgeTypes.map((definition) => {
    const key = normalizeOntologyLookupKey(definition?.name);
    const edited = edgeDefinitionByName.get(key);
    if (!edited) return definition;
    return {
      ...definition,
      ...edited,
      name: normalizeOntologyTypeName(edited?.name) || definition?.name,
      attributes: Array.isArray(edited?.attributes) ? edited.attributes : definition?.attributes ?? [],
      source_targets: Array.isArray(edited?.source_targets)
        ? edited.source_targets
        : definition?.source_targets ?? [],
    };
  });

  return {
    ...nextOntology,
    entity_types: mergedEntityTypes,
    edge_types: mergedEdgeTypes,
  };
}

export {
  normalizeProjectId,
  normalizePositiveInteger,
  normalizeNonNegativeInteger,
  normalizePromptLabel,
  getPreferredPromptLabel,
  parseJsonResponse,
  buildGraphDataApiPath,
  normalizeOntologyTypeName,
  normalizeOntologyTypeNames,
  buildUpdatedOntologyFromTypeNames,
  buildUpdatedOntologyFromDefinitions,
};
