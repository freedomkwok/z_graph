import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import * as d3 from "d3";

import EdgeStatsWindow from "./EdgeStatsWindow";
import GraphDetailPanel from "./GraphDetailPanel";
import GraphInspectorPanel from "./GraphInspectorPanel";
import NodeStatsWindow from "./NodeStatsWindow";
import { useTaskStore } from "./TaskStore/index";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";
const ZEP_EMBED_URL = import.meta.env.VITE_ZEP_EMBED_URL ?? "https://app.getzep.com";
const ZEP_GRAPH_URL_TEMPLATE = import.meta.env.VITE_ZEP_GRAPH_URL_TEMPLATE ?? "";
const TYPE_COLORS = [
  "#FF6B35",
  "#004E89",
  "#7B2D8E",
  "#1A936F",
  "#C5283D",
  "#E9724C",
  "#3498DB",
  "#9B59B6",
  "#27AE60",
  "#F39C12",
];
const GRAPH_DATA_CACHE = new Map();
const EDGE_STATS_WINDOW_DEFAULT_WIDTH = 760;
const EDGE_STATS_WINDOW_MIN_WIDTH = 500;
const NODE_STATS_WINDOW_DEFAULT_WIDTH = 460;
const NODE_STATS_WINDOW_MIN_WIDTH = 320;
const GRAPH_SEARCH_RESULT_LIMIT = 24;
const GRAPH_SEARCH_BACKEND_RESULT_LIMIT = 24;
const GRAPH_SEARCH_SCOPES = [
  { value: "all", label: "All" },
  { value: "node", label: "Nodes" },
  { value: "edge", label: "Edges" },
  { value: "episode", label: "Episodes" },
];
const EDGE_STATS_BUCKETS = [
  "sameRelationPair",
  "sameRelationDirected",
  "sameUndirectedPair",
  "sameRelationGlobal",
];
const MULTIPLE_NODE_SELECTION_WINDOW_ID = "multipleNodeSelection";

function isPanelDockedRightByMidpoint(positionX, panelWidth, containerWidth) {
  const safeContainerWidth = Math.max(0, Number(containerWidth) || 0);
  const safePanelWidth = Math.max(0, Number(panelWidth) || 0);
  const maxX = Math.max(0, safeContainerWidth - safePanelWidth);
  const safeX = Math.min(maxX, Math.max(0, Number(positionX) || 0));
  const panelCenterX = safeX + safePanelWidth / 2;
  return panelCenterX > safeContainerWidth / 2;
}

function withApiBase(path) {
  return `${API_BASE_URL}${path}`;
}

function resolveGraphEmbedUrl(project) {
  const storedAddress = String(project?.zep_graph_address ?? "").trim();
  if (storedAddress) return storedAddress;

  const graphId = String(project?.zep_graph_id ?? project?.graph_id ?? "").trim();
  if (!graphId) return ZEP_EMBED_URL;

  if (ZEP_GRAPH_URL_TEMPLATE) {
    if (ZEP_GRAPH_URL_TEMPLATE.includes("{graph_id}")) {
      return ZEP_GRAPH_URL_TEMPLATE.replaceAll("{graph_id}", encodeURIComponent(graphId));
    }
    return ZEP_GRAPH_URL_TEMPLATE;
  }

  return `${ZEP_EMBED_URL.replace(/\/$/, "")}/?graph_id=${encodeURIComponent(graphId)}`;
}

function extractGraphIdentifiersFromAddress(address) {
  const normalizedAddress = String(address ?? "").trim();
  if (!normalizedAddress) {
    return { graphId: "", workspaceId: "" };
  }

  let graphId = "";
  let workspaceId = "";
  try {
    const parsed = new URL(normalizedAddress);
    graphId = String(parsed.searchParams.get("graph_id") ?? "").trim();

    const segments = parsed.pathname.split("/").filter(Boolean);
    const projectIndex = segments.indexOf("projects");
    if (projectIndex >= 0 && projectIndex + 1 < segments.length) {
      workspaceId = decodeURIComponent(String(segments[projectIndex + 1] ?? "").trim());
    }

    const graphIndex = segments.indexOf("graphs");
    if (!graphId && graphIndex >= 0 && graphIndex + 1 < segments.length) {
      graphId = decodeURIComponent(String(segments[graphIndex + 1] ?? "").trim());
    }
  } catch {
    // Keep best-effort extraction only.
  }

  return {
    graphId: String(graphId ?? "").trim(),
    workspaceId: String(workspaceId ?? "").trim(),
  };
}

function getGraphId(project, selectedProjectId = "") {
  const resolvedGraphId = String(project?.zep_graph_id ?? project?.graph_id ?? "").trim();
  if (resolvedGraphId) return resolvedGraphId;

  const fromAddress = extractGraphIdentifiersFromAddress(project?.zep_graph_address).graphId;
  if (fromAddress) return fromAddress;
  return "";
}

function getProjectWorkspaceId(project) {
  const explicitWorkspaceId = String(project?.project_workspace_id ?? project?.workspace_id ?? "").trim();
  if (explicitWorkspaceId) return explicitWorkspaceId;
  return extractGraphIdentifiersFromAddress(project?.zep_graph_address).workspaceId;
}

function resolveProjectWorkspaceId(project, projectCatalogItems, selectedProjectId) {
  const fromCurrentProject = getProjectWorkspaceId(project);
  if (fromCurrentProject) return fromCurrentProject;

  const normalizedSelectedProjectId = String(selectedProjectId ?? "").trim();
  if (!normalizedSelectedProjectId || !Array.isArray(projectCatalogItems)) return "";

  const selectedProject = projectCatalogItems.find(
    (item) => String(item?.project_id ?? "").trim() === normalizedSelectedProjectId,
  );
  return getProjectWorkspaceId(selectedProject);
}

function getProjectGraphBackend(project) {
  return String(project?.graph_backend ?? "").trim().toLowerCase();
}

function resolveProjectGraphBackend(project, projectCatalogItems, selectedProjectId) {
  const fromCurrentProject = getProjectGraphBackend(project);
  if (fromCurrentProject) return fromCurrentProject;

  const normalizedSelectedProjectId = String(selectedProjectId ?? "").trim();
  if (!normalizedSelectedProjectId || !Array.isArray(projectCatalogItems)) return "";

  const selectedProject = projectCatalogItems.find(
    (item) => String(item?.project_id ?? "").trim() === normalizedSelectedProjectId,
  );
  return getProjectGraphBackend(selectedProject);
}

function buildGraphDataApiPath(graphId, projectWorkspaceId, projectGraphBackend, projectId) {
  const params = new URLSearchParams({ include_episode_data: "false" });
  const normalizedWorkspaceId = String(projectWorkspaceId ?? "").trim();
  if (normalizedWorkspaceId) {
    params.set("project_workspace_id", normalizedWorkspaceId);
  }
  const normalizedGraphBackend = String(projectGraphBackend ?? "").trim();
  if (normalizedGraphBackend) {
    params.set("graph_backend", normalizedGraphBackend);
  }
  const normalizedProjectId = String(projectId ?? "").trim();
  if (normalizedProjectId) {
    params.set("project_id", normalizedProjectId);
  }
  return `/api/data/${encodeURIComponent(String(graphId ?? "").trim())}?${params.toString()}`;
}

function buildGraphQuickSearchApiPath(graphId, query, scope, projectGraphBackend, projectId) {
  const params = new URLSearchParams({
    graph_id: String(graphId ?? "").trim(),
    query: String(query ?? "").trim(),
    scope: String(scope ?? "all").trim().toLowerCase(),
    limit: String(GRAPH_SEARCH_BACKEND_RESULT_LIMIT),
  });
  const normalizedGraphBackend = String(projectGraphBackend ?? "").trim();
  if (normalizedGraphBackend) {
    params.set("graph_backend", normalizedGraphBackend);
  }
  const normalizedProjectId = String(projectId ?? "").trim();
  if (normalizedProjectId) {
    params.set("project_id", normalizedProjectId);
  }
  return `/api/graph/search?${params.toString()}`;
}

function buildGraphCacheKey(graphId, projectWorkspaceId, projectGraphBackend) {
  return `${String(graphId ?? "").trim()}::${String(projectWorkspaceId ?? "").trim()}::${String(projectGraphBackend ?? "").trim()}`;
}

function getEntityType(node) {
  const labels = Array.isArray(node?.labels) ? node.labels : [];
  const custom = labels.find(
    (label) => label !== "Entity" && label !== "Node" && !String(label).startsWith("file:"),
  );
  return custom || "Entity";
}

function formatDateTime(value) {
  if (!value) return "-";
  try {
    const date = new Date(String(value));
    if (Number.isNaN(date.valueOf())) return String(value);
    return date.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return String(value);
  }
}

function formatFieldValue(value) {
  if (value === null || value === undefined || value === "") return "None";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function getGraphLabelValue(item) {
  const direct = String(item?.graph_label ?? "").trim();
  if (direct) return direct;
  const fromAttributes = String(item?.attributes?.graph_label ?? item?.attributes?.graphLabel ?? "").trim();
  if (fromAttributes) return fromAttributes;
  const fromProperties = String(item?.properties?.graph_label ?? item?.properties?.graphLabel ?? "").trim();
  return fromProperties;
}

function appendGraphLabelSuffix(baseLabel, item, graphLabelInput = "") {
  const existingGraphLabel = getGraphLabelValue(item);
  if (!existingGraphLabel) return String(baseLabel ?? "").trim();
  const appendedInput = String(graphLabelInput ?? "").trim();
  const mergedGraphLabel = appendedInput
    ? `${existingGraphLabel} ${appendedInput}`.trim()
    : existingGraphLabel;
  const normalizedBase = String(baseLabel ?? "").trim();
  if (!normalizedBase) return mergedGraphLabel;
  return `${normalizedBase} · ${mergedGraphLabel}`;
}

function getEdgePairKey(sourceId, targetId) {
  return sourceId < targetId ? `${sourceId}_${targetId}` : `${targetId}_${sourceId}`;
}

function getRelationLabel(edge) {
  return String(edge?.name || edge?.fact_type || "RELATED").trim() || "RELATED";
}

function getDirectedEdgeKey(sourceId, targetId) {
  return `${String(sourceId ?? "").trim()}->${String(targetId ?? "").trim()}`;
}

function getEdgeSelectionKey(edge) {
  const edgeUuid = String(edge?.uuid ?? "").trim();
  if (edgeUuid) return `uuid:${edgeUuid}`;
  const source = String(edge?.source_node_uuid ?? edge?.source_uuid ?? "").trim();
  const target = String(edge?.target_node_uuid ?? edge?.target_uuid ?? "").trim();
  const relation = getRelationLabel(edge);
  const fact = String(edge?.fact ?? "").trim();
  return `pair:${source}->${target}|rel:${relation}|fact:${fact}`;
}

function getUndirectedPairKeyFromEdge(edge) {
  const source = String(edge?.source_node_uuid ?? edge?.source_uuid ?? "").trim();
  const target = String(edge?.target_node_uuid ?? edge?.target_uuid ?? "").trim();
  if (!source || !target) return "";
  return getEdgePairKey(source, target);
}

function getNodeSelectionKey(node) {
  const nodeUuid = String(node?.uuid ?? node?.id ?? "").trim();
  if (nodeUuid) return `uuid:${nodeUuid}`;
  const nodeName = String(node?.name ?? "").trim();
  const nodeType = getEntityType(node);
  return `node:${nodeType}|name:${nodeName}`;
}

function getNodeUuid(node) {
  return String(node?.uuid ?? node?.id ?? "").trim();
}

function getNodeDisplayName(node) {
  return String(node?.name ?? "").trim() || "Unnamed";
}

function getNodeDisplayLabel(node, graphLabelInput = "") {
  return appendGraphLabelSuffix(getNodeDisplayName(node), node, graphLabelInput);
}

function getEdgeDisplayLabel(edge, graphLabelInput = "") {
  return appendGraphLabelSuffix(getRelationLabel(edge), edge, graphLabelInput);
}

function getEdgeNodeUuids(edge) {
  return {
    source: String(edge?.source_node_uuid ?? edge?.source_uuid ?? "").trim(),
    target: String(edge?.target_node_uuid ?? edge?.target_uuid ?? "").trim(),
  };
}

function edgeTouchesNode(edge, nodeUuid) {
  if (!nodeUuid) return false;
  const { source, target } = getEdgeNodeUuids(edge);
  return source === nodeUuid || target === nodeUuid;
}

function edgeIsBetweenNodes(edge, leftNodeUuid, rightNodeUuid) {
  if (!leftNodeUuid || !rightNodeUuid) return false;
  const { source, target } = getEdgeNodeUuids(edge);
  return (
    (source === leftNodeUuid && target === rightNodeUuid) ||
    (source === rightNodeUuid && target === leftNodeUuid)
  );
}

function dedupeEdgesBySelectionKey(edges) {
  const dedupedByKey = new Map();
  (Array.isArray(edges) ? edges : []).forEach((edge) => {
    const key = getEdgeSelectionKey(edge);
    if (!key || dedupedByKey.has(key)) return;
    dedupedByKey.set(key, edge);
  });
  return Array.from(dedupedByKey.values());
}

function buildGroupedNodeEdgeSections(nodes, graphEdges) {
  const selectedNodes = Array.isArray(nodes) ? nodes.slice(0, 2) : [];
  if (!selectedNodes.length) {
    return {
      nodeOne: null,
      nodeTwo: null,
      nodeOneOnlyEdges: [],
      sharedEdges: [],
      nodeTwoOnlyEdges: [],
      hasTwoNodes: false,
    };
  }

  const nodeOne = selectedNodes[0] ?? null;
  const nodeTwo = selectedNodes[1] ?? null;
  const nodeOneUuid = getNodeUuid(nodeOne);
  const nodeTwoUuid = getNodeUuid(nodeTwo);
  const edges = Array.isArray(graphEdges) ? graphEdges : [];

  if (!nodeTwo) {
    return {
      nodeOne,
      nodeTwo: null,
      nodeOneOnlyEdges: dedupeEdgesBySelectionKey(
        edges.filter((edge) => edgeTouchesNode(edge, nodeOneUuid)),
      ),
      sharedEdges: [],
      nodeTwoOnlyEdges: [],
      hasTwoNodes: false,
    };
  }

  const sharedEdges = dedupeEdgesBySelectionKey(
    edges.filter((edge) => edgeIsBetweenNodes(edge, nodeOneUuid, nodeTwoUuid)),
  );
  const sharedEdgeKeys = new Set(sharedEdges.map((edge) => getEdgeSelectionKey(edge)).filter(Boolean));
  const nodeOneOnlyEdges = dedupeEdgesBySelectionKey(
    edges.filter((edge) => {
      if (!edgeTouchesNode(edge, nodeOneUuid)) return false;
      const key = getEdgeSelectionKey(edge);
      return !sharedEdgeKeys.has(key);
    }),
  );
  const nodeTwoOnlyEdges = dedupeEdgesBySelectionKey(
    edges.filter((edge) => {
      if (!edgeTouchesNode(edge, nodeTwoUuid)) return false;
      const key = getEdgeSelectionKey(edge);
      return !sharedEdgeKeys.has(key);
    }),
  );

  return {
    nodeOne,
    nodeTwo,
    nodeOneOnlyEdges,
    sharedEdges,
    nodeTwoOnlyEdges,
    hasTwoNodes: true,
  };
}

function buildPairMultiSelectionCandidate({
  clickedEdge,
  currentMultiSelection,
  currentSingleEdge,
}) {
  const clickedPairKey = getUndirectedPairKeyFromEdge(clickedEdge);
  const clickedEdgeKey = getEdgeSelectionKey(clickedEdge);
  if (!clickedPairKey || !clickedEdgeKey) return null;

  const currentMultiPairKey = String(currentMultiSelection?.pairKey ?? "").trim();
  const currentMultiEdges = Array.isArray(currentMultiSelection?.edges)
    ? currentMultiSelection.edges
    : [];
  const canExtendCurrentMulti =
    currentMultiPairKey === clickedPairKey && currentMultiEdges.length > 0;

  const currentSinglePairKey = getUndirectedPairKeyFromEdge(currentSingleEdge);
  const currentSingleEdgeKey = getEdgeSelectionKey(currentSingleEdge);
  const canStartFromCurrentSingle =
    !canExtendCurrentMulti &&
    currentSingleEdge &&
    currentSinglePairKey === clickedPairKey &&
    currentSingleEdgeKey &&
    currentSingleEdgeKey !== clickedEdgeKey;

  if (!canExtendCurrentMulti && !canStartFromCurrentSingle) return null;

  const seedEdges = canExtendCurrentMulti
    ? currentMultiEdges
    : [currentSingleEdge, clickedEdge];
  const dedupedByKey = new Map();
  seedEdges.forEach((edge) => {
    const key = getEdgeSelectionKey(edge);
    if (!key) return;
    if (!dedupedByKey.has(key)) {
      dedupedByKey.set(key, edge);
    }
  });
  if (!dedupedByKey.has(clickedEdgeKey)) {
    dedupedByKey.set(clickedEdgeKey, clickedEdge);
  }
  const nextEdges = Array.from(dedupedByKey.values());
  if (nextEdges.length < 2) return null;

  return {
    pairKey: clickedPairKey,
    selectedEdgeKey: clickedEdgeKey,
    edges: nextEdges,
  };
}

function buildNodeMultiSelectionCandidate({
  clickedNode,
  currentMultiSelection,
  currentSingleNode,
}) {
  const clickedNodeKey = getNodeSelectionKey(clickedNode);
  if (!clickedNodeKey) return null;

  const currentMultiNodes = Array.isArray(currentMultiSelection?.nodes)
    ? currentMultiSelection.nodes
    : [];
  const canExtendCurrentMulti = currentMultiNodes.length > 0;

  const currentSingleNodeKey = getNodeSelectionKey(currentSingleNode);
  const canStartFromCurrentSingle =
    !canExtendCurrentMulti &&
    currentSingleNode &&
    currentSingleNodeKey &&
    currentSingleNodeKey !== clickedNodeKey;

  if (!canExtendCurrentMulti && !canStartFromCurrentSingle) return null;

  const seedNodes = canExtendCurrentMulti ? currentMultiNodes : [currentSingleNode, clickedNode];
  const dedupedByKey = new Map();
  seedNodes.forEach((node) => {
    const key = getNodeSelectionKey(node);
    if (!key) return;
    if (!dedupedByKey.has(key)) {
      dedupedByKey.set(key, node);
    }
  });
  if (!dedupedByKey.has(clickedNodeKey)) {
    dedupedByKey.set(clickedNodeKey, clickedNode);
  }
  const nextNodes = Array.from(dedupedByKey.values());
  if (nextNodes.length < 2) return null;
  const cappedNodes = nextNodes.slice(-2);
  const cappedKeys = new Set(cappedNodes.map((node) => getNodeSelectionKey(node)).filter(Boolean));
  const nextSelectedNodeKey = cappedKeys.has(clickedNodeKey)
    ? clickedNodeKey
    : getNodeSelectionKey(cappedNodes[cappedNodes.length - 1] ?? null);

  return {
    selectedNodeKey: nextSelectedNodeKey,
    nodes: cappedNodes,
  };
}

function buildEntityTypeList(nodes) {
  const typeToColor = new Map();
  const typeToIndex = new Map();
  const types = [];

  nodes.forEach((node) => {
    const type = getEntityType(node);
    const existingIndex = typeToIndex.get(type);
    if (existingIndex !== undefined) {
      types[existingIndex].count += 1;
      return;
    }
    const color = TYPE_COLORS[typeToColor.size % TYPE_COLORS.length];
    typeToColor.set(type, color);
    typeToIndex.set(type, types.length);
    types.push({ name: type, color, count: 1 });
  });

  return { types, typeToColor };
}

function buildEdgeStatsForEdge(selectedEdge, graphEdges) {
  if (!selectedEdge) return null;
  if (selectedEdge?.isSelfLoopGroup) return null;

  const selectedSource = String(selectedEdge.source_node_uuid ?? "").trim();
  const selectedTarget = String(selectedEdge.target_node_uuid ?? "").trim();
  const selectedRelation = getRelationLabel(selectedEdge);
  if (!selectedSource || !selectedTarget) return null;

  const selectedDirectedKey = getDirectedEdgeKey(selectedSource, selectedTarget);
  const selectedUndirectedKey = getEdgePairKey(selectedSource, selectedTarget);
  const edges = Array.isArray(graphEdges) ? graphEdges : [];

  const sameUndirectedPairEdges = [];
  const sameRelationDirectedEdges = [];
  const sameRelationPairEdges = [];
  const sameRelationGlobalEdges = [];

  edges.forEach((edge) => {
    const source = String(edge?.source_node_uuid ?? "").trim();
    const target = String(edge?.target_node_uuid ?? "").trim();
    if (!source || !target) return;

    const relation = getRelationLabel(edge);
    const directedKey = getDirectedEdgeKey(source, target);
    const undirectedKey = getEdgePairKey(source, target);
    const isSameRelation = relation === selectedRelation;

    if (directedKey === selectedDirectedKey && isSameRelation) {
      sameRelationDirectedEdges.push(edge);
    }

    if (undirectedKey === selectedUndirectedKey) {
      sameUndirectedPairEdges.push(edge);
      if (isSameRelation) {
        sameRelationPairEdges.push(edge);
      }
    }

    if (isSameRelation) {
      sameRelationGlobalEdges.push(edge);
    }
  });

  return {
    relation: selectedRelation,
    sameUndirectedPairEdges,
    sameRelationDirectedEdges,
    sameRelationPairEdges,
    sameRelationGlobalEdges,
    sameUndirectedPairCount: sameUndirectedPairEdges.length,
    sameRelationDirectedCount: sameRelationDirectedEdges.length,
    sameRelationPairCount: sameRelationPairEdges.length,
    sameRelationGlobalCount: sameRelationGlobalEdges.length,
  };
}

export default function GraphEmbedPanel() {
  const { state, refreshGraphFrame, addSystemLog, reportLiveGraphBuildCounts, trackedFetch } = useTaskStore();
  const selectedProjectId = String(state.form?.projectId ?? "").trim();
  const currentProjectId = String(state.currentProject?.project_id ?? "").trim();
  const isProjectHydratedForSelection =
    !selectedProjectId || selectedProjectId === currentProjectId;
  const projectForGraph = isProjectHydratedForSelection ? state.currentProject : null;
  const storedGraphAddress = String(projectForGraph?.zep_graph_address ?? "").trim();
  const graphId = getGraphId(projectForGraph, selectedProjectId);
  const projectWorkspaceId = resolveProjectWorkspaceId(
    projectForGraph,
    state.projectCatalog?.items,
    selectedProjectId,
  );
  const projectGraphBackend = resolveProjectGraphBackend(
    projectForGraph,
    state.projectCatalog?.items,
    selectedProjectId,
  );
  const graphUrl = resolveGraphEmbedUrl(projectForGraph);
  const refreshDataWhileBuild = Boolean(state.form?.refreshDataWhileBuild);
  const refreshDataPollSecondsValue = Number(state.form?.refreshDataPollSeconds);
  const refreshDataPollSeconds =
    Number.isFinite(refreshDataPollSecondsValue) && refreshDataPollSecondsValue > 0
      ? Math.floor(refreshDataPollSecondsValue)
      : 20;
  const isLiveBuildDataRefreshEnabled = state.graphTask.status === "running" && refreshDataWhileBuild;
  const canOpenZepGraph = Boolean(graphId || storedGraphAddress);
  const showOpenInZepButton = projectGraphBackend === "zep_cloud";
  const graphCacheKey = buildGraphCacheKey(graphId, projectWorkspaceId, projectGraphBackend);
  const graphDataPollIntervalMs = Math.max(1000, refreshDataPollSeconds * 1000);
  const graphLabelInput = String(state.form?.graphLabel ?? "").trim();

  const containerRef = useRef(null);
  const svgRef = useRef(null);
  const simulationRef = useRef(null);
  const selectedNodeUuidRef = useRef("");
  const selectedNodeHighlightKeysRef = useRef(new Set());
  const clearSelectionRef = useRef(() => {});
  const highlightEdgeInGraphRef = useRef(() => {});
  const highlightEdgesInGraphRef = useRef(() => {});
  const highlightNodeInGraphRef = useRef(() => {});
  const highlightNodesInGraphRef = useRef(() => {});
  const addSystemLogRef = useRef(addSystemLog);
  const fetchInFlightRef = useRef(false);
  const fetchAbortControllerRef = useRef(null);
  const backendSearchAbortControllerRef = useRef(null);
  const backendSearchRequestSerialRef = useRef(0);
  const inFlightRequestScopeRef = useRef("");
  const fetchRequestSerialRef = useRef(0);
  const previousGraphTaskStatusRef = useRef(state.graphTask.status);
  const prevGraphTaskStatusForCacheRef = useRef(state.graphTask.status);
  const graphTaskStatusRef = useRef(state.graphTask.status);
  const prevOntologyTaskStatusRef = useRef(state.ontologyTask.status);
  /** After ontology generate finishes, project hydration retriggers this panel; skip graph /api/data reload. */
  const skipGraphReloadAfterOntologyRef = useRef(false);
  const reportLiveGraphBuildCountsRef = useRef(reportLiveGraphBuildCounts);
  const edgeStatsWindowRefs = useRef(new Map());
  const edgeStatsWindowDragRef = useRef(null);
  const edgeStatsWindowResizeRef = useRef(null);
  const detailPanelRef = useRef(null);
  const detailPanelDragRef = useRef(null);
  const graphSearchContainerRef = useRef(null);
  const lastMultipleSelectionWindowRef = useRef({
    x: 28,
    y: 72,
    width: EDGE_STATS_WINDOW_DEFAULT_WIDTH,
  });
  const lastMultipleNodeSelectionWindowRef = useRef({
    x: 56,
    y: 84,
    width: NODE_STATS_WINDOW_DEFAULT_WIDTH,
  });
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedItem, setSelectedItem] = useState(null);
  const [showEdgeLabels, setShowEdgeLabels] = useState(true);
  const [selectedEntityTypes, setSelectedEntityTypes] = useState(null);
  const [selectedEdgeTypes, setSelectedEdgeTypes] = useState(null);
  const [entityTypeSearchText, setEntityTypeSearchText] = useState("");
  const [edgeTypeSearchText, setEdgeTypeSearchText] = useState("");
  const [graphSearchText, setGraphSearchText] = useState("");
  const [debouncedGraphSearchText, setDebouncedGraphSearchText] = useState("");
  const [graphSearchScope, setGraphSearchScope] = useState("all");
  const [graphSearchResult, setGraphSearchResult] = useState(null);
  const [graphSearchOpen, setGraphSearchOpen] = useState(false);
  const [backendGraphSearchOptions, setBackendGraphSearchOptions] = useState([]);
  const [isBackendGraphSearchLoading, setIsBackendGraphSearchLoading] = useState(false);
  const [detailPanelSide, setDetailPanelSide] = useState("right");
  const [detailPanelPosition, setDetailPanelPosition] = useState(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorTab, setInspectorTab] = useState("entity");
  const [edgeStatsWindowsByBucket, setEdgeStatsWindowsByBucket] = useState({});
  const [multipleSelectionWindow, setMultipleSelectionWindow] = useState(null);
  const [multiEdgeSelection, setMultiEdgeSelection] = useState(null);
  const [multipleNodeSelectionWindow, setMultipleNodeSelectionWindow] = useState(null);
  const [multiNodeSelection, setMultiNodeSelection] = useState(null);
  const [preferSingleEdgeHighlight, setPreferSingleEdgeHighlight] = useState(false);
  const [focusedWindowId, setFocusedWindowId] = useState(null);
  const selectedItemRef = useRef(selectedItem);
  const multiEdgeSelectionRef = useRef(multiEdgeSelection);
  const multiNodeSelectionRef = useRef(multiNodeSelection);
  const setEdgeStatsWindowNodeRef = useCallback((windowId, node) => {
    const refs = edgeStatsWindowRefs.current;
    if (node) {
      refs.set(windowId, node);
      return;
    }
    refs.delete(windowId);
  }, []);
  const getEdgeStatsWindowNode = useCallback((windowId) => {
    return edgeStatsWindowRefs.current.get(windowId) ?? null;
  }, []);
  const patchBucketWindow = useCallback((bucket, updater) => {
    setEdgeStatsWindowsByBucket((prev) => {
      const current = prev?.[bucket] ?? null;
      const nextValue = typeof updater === "function" ? updater(current) : updater;
      const normalized = nextValue ?? null;
      if (normalized === current) return prev;
      if (!normalized) {
        if (!(bucket in prev)) return prev;
        const next = { ...prev };
        delete next[bucket];
        return next;
      }
      return {
        ...prev,
        [bucket]: normalized,
      };
    });
  }, []);

  const { types: entityTypes, typeToColor } = useMemo(
    () => buildEntityTypeList(Array.isArray(graphData?.nodes) ? graphData.nodes : []),
    [graphData],
  );
  const edgeTypeOptions = useMemo(() => {
    const edges = Array.isArray(graphData?.edges) ? graphData.edges : [];
    const countByType = new Map();
    edges.forEach((edge) => {
      const relation = getRelationLabel(edge);
      countByType.set(relation, (countByType.get(relation) ?? 0) + 1);
    });
    return Array.from(countByType.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name));
  }, [graphData]);
  const activeEntityTypeSet = useMemo(() => {
    if (!entityTypes.length) return new Set();
    if (selectedEntityTypes === null) {
      return new Set(entityTypes.map((type) => type.name));
    }
    return new Set(selectedEntityTypes);
  }, [entityTypes, selectedEntityTypes]);
  const activeEdgeTypeSet = useMemo(() => {
    if (!edgeTypeOptions.length) return new Set();
    if (selectedEdgeTypes === null) {
      return new Set(edgeTypeOptions.map((type) => type.name));
    }
    return new Set(selectedEdgeTypes);
  }, [edgeTypeOptions, selectedEdgeTypes]);
  const visibleEntityTypeOptions = useMemo(() => {
    const normalized = entityTypeSearchText.trim().toLowerCase();
    if (!normalized) return entityTypes;
    return entityTypes.filter((type) => type.name.toLowerCase().includes(normalized));
  }, [entityTypeSearchText, entityTypes]);
  const visibleEdgeTypeOptions = useMemo(() => {
    const normalized = edgeTypeSearchText.trim().toLowerCase();
    if (!normalized) return edgeTypeOptions;
    return edgeTypeOptions.filter((type) => type.name.toLowerCase().includes(normalized));
  }, [edgeTypeOptions, edgeTypeSearchText]);
  const graphSearchOptions = useMemo(() => {
    const normalized = graphSearchText.trim().toLowerCase();
    if (!normalized) return [];

    const nodes = Array.isArray(graphData?.nodes) ? graphData.nodes : [];
    const edges = Array.isArray(graphData?.edges) ? graphData.edges : [];
    const nodeNameById = new Map(
      nodes.map((node) => [
        String(node?.uuid ?? node?.id ?? "").trim(),
        getNodeDisplayLabel(node, graphLabelInput),
      ]),
    );
    const includeNodes = graphSearchScope === "all" || graphSearchScope === "node";
    const includeEdges = graphSearchScope === "all" || graphSearchScope === "edge";
    const includeEpisodes = graphSearchScope === "all" || graphSearchScope === "episode";
    const options = [];

    if (includeNodes) {
      nodes.forEach((node) => {
        const uuid = getNodeUuid(node);
        if (!uuid) return;
        const searchable = [
          getNodeDisplayLabel(node, graphLabelInput),
          String(node?.summary ?? ""),
          JSON.stringify(node?.attributes ?? {}),
        ]
          .join(" ")
          .toLowerCase();
        if (!searchable.includes(normalized)) return;
        const entityType = getEntityType(node);
        options.push({
          key: `node:${uuid}`,
          kind: "node",
          label: getNodeDisplayLabel(node, graphLabelInput),
          subtitle: entityType,
          anchorNodeIds: [uuid],
          nodeData: node,
        });
      });
    }

    if (includeEdges) {
      edges.forEach((edge) => {
        const edgeKey = getEdgeSelectionKey(edge);
        const { source, target } = getEdgeNodeUuids(edge);
        const sourceName =
          nodeNameById.get(source) ?? String(edge?.source_node_name ?? source ?? "Unknown");
        const targetName =
          nodeNameById.get(target) ?? String(edge?.target_node_name ?? target ?? "Unknown");
        const relation = getRelationLabel(edge);
        const relationDisplay = getEdgeDisplayLabel(edge, graphLabelInput);
        const fact = String(edge?.fact ?? "").trim();
        const searchable = [relationDisplay, relation, fact, sourceName, targetName, edgeKey]
          .join(" ")
          .toLowerCase();
        if (!searchable.includes(normalized)) return;
        options.push({
          key: `edge:${edgeKey}`,
          kind: "edge",
          label: `${sourceName} -> ${targetName}`,
          subtitle: fact || relationDisplay,
          anchorNodeIds: [source, target].filter(Boolean),
          edgeData: edge,
        });
      });
    }

    if (includeEpisodes) {
      const episodeMap = new Map();
      edges.forEach((edge) => {
        const episodes = Array.isArray(edge?.episodes) ? edge.episodes : [];
        const { source, target } = getEdgeNodeUuids(edge);
        episodes.forEach((episodeId) => {
          const normalizedEpisode = String(episodeId ?? "").trim();
          if (!normalizedEpisode) return;
          const existing =
            episodeMap.get(normalizedEpisode) ??
            { id: normalizedEpisode, edgeCount: 0, anchorNodeIds: new Set(), graphLabel: "" };
          existing.edgeCount += 1;
          if (source) existing.anchorNodeIds.add(source);
          if (target) existing.anchorNodeIds.add(target);
          if (!existing.graphLabel) {
            existing.graphLabel = getGraphLabelValue(edge);
          }
          episodeMap.set(normalizedEpisode, existing);
        });
      });
      Array.from(episodeMap.values()).forEach((episode) => {
        if (!episode.id.toLowerCase().includes(normalized)) return;
        options.push({
          key: `episode:${episode.id}`,
          kind: "episode",
          label: appendGraphLabelSuffix(
            `Episode ${episode.id}`,
            { graph_label: episode.graphLabel },
            graphLabelInput,
          ),
          subtitle: `${episode.edgeCount} related edge${episode.edgeCount === 1 ? "" : "s"}`,
          anchorNodeIds: Array.from(episode.anchorNodeIds),
        });
      });
    }

    return options
      .sort((left, right) => left.label.localeCompare(right.label))
      .slice(0, GRAPH_SEARCH_RESULT_LIMIT);
  }, [graphData, graphSearchScope, graphSearchText, graphLabelInput]);
  const mergedGraphSearchOptions = useMemo(() => {
    const localOptions = Array.isArray(graphSearchOptions) ? graphSearchOptions : [];
    const remoteOptions = Array.isArray(backendGraphSearchOptions) ? backendGraphSearchOptions : [];
    if (!localOptions.length) return remoteOptions;
    if (!remoteOptions.length) return localOptions;
    const dedupedByKey = new Map();
    localOptions.forEach((option) => {
      dedupedByKey.set(String(option?.key ?? ""), option);
    });
    remoteOptions.forEach((option) => {
      const optionKey = String(option?.key ?? "").trim();
      if (!optionKey || dedupedByKey.has(optionKey)) return;
      dedupedByKey.set(optionKey, option);
    });
    return Array.from(dedupedByKey.values());
  }, [backendGraphSearchOptions, graphSearchOptions]);
  const filteredGraphData = useMemo(() => {
    const nodes = Array.isArray(graphData?.nodes) ? graphData.nodes : [];
    const edges = Array.isArray(graphData?.edges) ? graphData.edges : [];
    if (!nodes.length) {
      return { nodes: [], edges: [] };
    }
    const typeFilteredNodes = nodes.filter((node) => activeEntityTypeSet.has(getEntityType(node)));
    const typeVisibleNodeIds = new Set(typeFilteredNodes.map((node) => getNodeUuid(node)));
    const typeFilteredEdges = edges.filter((edge) => {
      const source = String(edge?.source_node_uuid ?? "");
      const target = String(edge?.target_node_uuid ?? "");
      const relation = getRelationLabel(edge);
      return (
        typeVisibleNodeIds.has(source) &&
        typeVisibleNodeIds.has(target) &&
        activeEdgeTypeSet.has(relation)
      );
    });
    if (!graphSearchResult || !Array.isArray(graphSearchResult.anchorNodeIds)) {
      return { nodes: typeFilteredNodes, edges: typeFilteredEdges };
    }
    const anchorNodeIds = graphSearchResult.anchorNodeIds
      .map((value) => String(value ?? "").trim())
      .filter(Boolean);
    if (!anchorNodeIds.length) {
      return { nodes: typeFilteredNodes, edges: typeFilteredEdges };
    }
    const anchorNodeSet = new Set(anchorNodeIds);
    const visibleNodeIds = new Set(anchorNodeIds);
    typeFilteredEdges.forEach((edge) => {
      const { source, target } = getEdgeNodeUuids(edge);
      if (!source || !target) return;
      if (anchorNodeSet.has(source) || anchorNodeSet.has(target)) {
        visibleNodeIds.add(source);
        visibleNodeIds.add(target);
      }
    });
    const filteredNodes = typeFilteredNodes.filter((node) => visibleNodeIds.has(getNodeUuid(node)));
    const filteredEdges = typeFilteredEdges.filter((edge) => {
      const { source, target } = getEdgeNodeUuids(edge);
      return visibleNodeIds.has(source) && visibleNodeIds.has(target);
    });
    return { nodes: filteredNodes, edges: filteredEdges };
  }, [activeEdgeTypeSet, activeEntityTypeSet, graphData, graphSearchResult]);
  const nodeEdgeStatsByNode = useMemo(() => {
    const stats = new Map();
    const edges = Array.isArray(graphData?.edges) ? graphData.edges : [];
    edges.forEach((edge) => {
      const source = String(edge?.source_node_uuid ?? "");
      const target = String(edge?.target_node_uuid ?? "");
      if (!source || !target) return;

      const sourceStats = stats.get(source) ?? { total: 0, incoming: 0, outgoing: 0 };
      const targetStats = stats.get(target) ?? { total: 0, incoming: 0, outgoing: 0 };

      sourceStats.total += 1;
      sourceStats.outgoing += 1;
      if (source === target) {
        sourceStats.incoming += 1;
        stats.set(source, sourceStats);
        return;
      }

      targetStats.total += 1;
      targetStats.incoming += 1;
      stats.set(source, sourceStats);
      stats.set(target, targetStats);
    });
    return stats;
  }, [graphData]);

  useEffect(() => {
    addSystemLogRef.current = addSystemLog;
  }, [addSystemLog]);

  useEffect(() => {
    selectedItemRef.current = selectedItem;
  }, [selectedItem]);

  useEffect(() => {
    if (!graphSearchOpen) return undefined;
    const onMouseDown = (event) => {
      const container = graphSearchContainerRef.current;
      if (!container) return;
      if (container.contains(event.target)) return;
      setGraphSearchOpen(false);
    };
    window.addEventListener("mousedown", onMouseDown);
    return () => window.removeEventListener("mousedown", onMouseDown);
  }, [graphSearchOpen]);

  useEffect(() => {
    const normalizedQuery = String(graphSearchText ?? "").trim();
    if (!normalizedQuery) {
      setDebouncedGraphSearchText("");
      return undefined;
    }
    const debounceTimer = window.setTimeout(() => {
      setDebouncedGraphSearchText(graphSearchText);
    }, 1000);
    return () => window.clearTimeout(debounceTimer);
  }, [graphSearchText]);

  useEffect(() => {
    const normalizedQuery = String(debouncedGraphSearchText ?? "").trim();
    if (!graphSearchOpen || !normalizedQuery || !graphId || !isProjectHydratedForSelection) {
      try {
        backendSearchAbortControllerRef.current?.abort();
      } catch {
        // Ignore abort cleanup failures.
      }
      backendSearchAbortControllerRef.current = null;
      backendSearchRequestSerialRef.current += 1;
      setIsBackendGraphSearchLoading(false);
      setBackendGraphSearchOptions([]);
      return undefined;
    }

    const requestSerial = backendSearchRequestSerialRef.current + 1;
    backendSearchRequestSerialRef.current = requestSerial;
    const controller = new AbortController();
    backendSearchAbortControllerRef.current = controller;
    setIsBackendGraphSearchLoading(true);
    setBackendGraphSearchOptions([]);

    const run = async () => {
      try {
        const response = await trackedFetch(
          withApiBase(
            buildGraphQuickSearchApiPath(
              graphId,
              normalizedQuery,
              graphSearchScope,
              projectGraphBackend,
              selectedProjectId,
            ),
          ),
          {
            cache: "no-store",
            headers: { Accept: "application/json" },
            signal: controller.signal,
          },
          { source: "graph_data_polling" },
        );
        const payload = await response.json();
        if (controller.signal.aborted || requestSerial !== backendSearchRequestSerialRef.current) {
          return;
        }
        if (!response.ok || !payload?.success) {
          throw new Error(payload?.error ?? "Failed to search graph");
        }
        const nodeNameById = new Map(
          (Array.isArray(graphData?.nodes) ? graphData.nodes : []).map((node) => [
            String(node?.uuid ?? node?.id ?? "").trim(),
            getNodeDisplayLabel(node, graphLabelInput),
          ]),
        );
        const remoteOptions = [];
        const remoteNodes = Array.isArray(payload?.data?.nodes) ? payload.data.nodes : [];
        const remoteEdges = Array.isArray(payload?.data?.edges) ? payload.data.edges : [];
        const remoteEpisodes = Array.isArray(payload?.data?.episodes) ? payload.data.episodes : [];

        remoteNodes.forEach((node) => {
          const uuid = String(node?.uuid ?? "").trim();
          if (!uuid) return;
          const labels = Array.isArray(node?.labels) ? node.labels : [];
          const nonGenericLabel = labels.find((label) => label !== "Entity" && label !== "Node");
          remoteOptions.push({
            key: `remote:node:${uuid}`,
            kind: "node",
            label: getNodeDisplayLabel(node, graphLabelInput),
            subtitle: nonGenericLabel || String(node?.summary ?? "").trim() || "node",
            anchorNodeIds: [uuid],
            nodeData: node,
          });
        });

        remoteEdges.forEach((edge) => {
          const edgeUuid = String(edge?.uuid ?? "").trim();
          const sourceNodeUuid = String(edge?.source_node_uuid ?? "").trim();
          const targetNodeUuid = String(edge?.target_node_uuid ?? "").trim();
          const sourceName = nodeNameById.get(sourceNodeUuid) ?? (sourceNodeUuid || "Unknown");
          const targetName = nodeNameById.get(targetNodeUuid) ?? (targetNodeUuid || "Unknown");
          const relationText = String(edge?.fact ?? "").trim() || String(edge?.name ?? "").trim() || "edge";
          remoteOptions.push({
            key: `remote:edge:${edgeUuid || `${sourceNodeUuid}:${targetNodeUuid}:${relationText}`}`,
            kind: "edge",
            label: `${sourceName} -> ${targetName}`,
            subtitle: relationText,
            anchorNodeIds: [sourceNodeUuid, targetNodeUuid].filter(Boolean),
            edgeData: edge,
          });
        });

        remoteEpisodes.forEach((episode) => {
          const episodeId = String(episode?.id ?? "").trim();
          if (!episodeId) return;
          remoteOptions.push({
            key: `remote:episode:${episodeId}`,
            kind: "episode",
            label: `Episode ${episodeId}`,
            subtitle: String(episode?.subtitle ?? "").trim() || String(episode?.preview ?? "").trim() || "episode",
            anchorNodeIds: Array.isArray(episode?.anchor_node_ids)
              ? episode.anchor_node_ids.map((id) => String(id ?? "").trim()).filter(Boolean)
              : [],
          });
        });
        setBackendGraphSearchOptions(remoteOptions.slice(0, GRAPH_SEARCH_RESULT_LIMIT));
      } catch (error) {
        if (controller.signal.aborted || requestSerial !== backendSearchRequestSerialRef.current) {
          return;
        }
        setBackendGraphSearchOptions([]);
      } finally {
        if (requestSerial === backendSearchRequestSerialRef.current) {
          setIsBackendGraphSearchLoading(false);
        }
      }
    };

    run();
    return () => {
      try {
        controller.abort();
      } catch {
        // Ignore abort cleanup failures.
      }
    };
  }, [
    graphData?.nodes,
    graphId,
    graphLabelInput,
    graphSearchOpen,
    graphSearchScope,
    debouncedGraphSearchText,
    isProjectHydratedForSelection,
    projectGraphBackend,
    selectedProjectId,
    trackedFetch,
  ]);

  useEffect(() => {
    multiEdgeSelectionRef.current = multiEdgeSelection;
  }, [multiEdgeSelection]);

  useEffect(() => {
    multiNodeSelectionRef.current = multiNodeSelection;
  }, [multiNodeSelection]);

  useEffect(() => {
    if (!multipleSelectionWindow) return;
    const x = Number(multipleSelectionWindow.x);
    const y = Number(multipleSelectionWindow.y);
    const width = Number(multipleSelectionWindow.width);
    lastMultipleSelectionWindowRef.current = {
      x: Number.isFinite(x) ? x : 28,
      y: Number.isFinite(y) ? y : 72,
      width:
        Number.isFinite(width) && width > 0
          ? width
          : EDGE_STATS_WINDOW_DEFAULT_WIDTH,
    };
  }, [multipleSelectionWindow]);

  useEffect(() => {
    if (!multipleNodeSelectionWindow) return;
    const x = Number(multipleNodeSelectionWindow.x);
    const y = Number(multipleNodeSelectionWindow.y);
    const width = Number(multipleNodeSelectionWindow.width);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(width)) return;
    lastMultipleNodeSelectionWindowRef.current = { x, y, width };
  }, [multipleNodeSelectionWindow]);

  useEffect(() => {
    graphTaskStatusRef.current = state.graphTask.status;
  }, [state.graphTask.status]);

  useEffect(() => {
    reportLiveGraphBuildCountsRef.current = reportLiveGraphBuildCounts;
  }, [reportLiveGraphBuildCounts]);

  useEffect(() => {
    const prev = prevOntologyTaskStatusRef.current;
    const cur = state.ontologyTask.status;
    prevOntologyTaskStatusRef.current = cur;
    if (prev === "running" && cur === "success") {
      skipGraphReloadAfterOntologyRef.current = true;
    }
  }, [state.ontologyTask.status]);

  useEffect(() => {
    const prev = prevGraphTaskStatusForCacheRef.current;
    const cur = state.graphTask.status;
    prevGraphTaskStatusForCacheRef.current = cur;
    if (prev !== "running" && cur === "running") {
      GRAPH_DATA_CACHE.clear();
    }
  }, [state.graphTask.status]);

  useEffect(() => {
    if (!entityTypes.length) {
      if (selectedEntityTypes !== null) {
        setSelectedEntityTypes(null);
      }
      return;
    }
    if (selectedEntityTypes === null) return;
    const validNames = new Set(entityTypes.map((type) => type.name));
    setSelectedEntityTypes((prev) => {
      if (prev === null) return null;
      const next = prev.filter((name) => validNames.has(name));
      return next.length === prev.length ? prev : next;
    });
  }, [entityTypes, selectedEntityTypes]);
  useEffect(() => {
    if (!edgeTypeOptions.length) {
      if (selectedEdgeTypes !== null) {
        setSelectedEdgeTypes(null);
      }
      return;
    }
    if (selectedEdgeTypes === null) return;
    const validNames = new Set(edgeTypeOptions.map((type) => type.name));
    setSelectedEdgeTypes((prev) => {
      if (prev === null) return null;
      const next = prev.filter((name) => validNames.has(name));
      return next.length === prev.length ? prev : next;
    });
  }, [edgeTypeOptions, selectedEdgeTypes]);

  const fetchGraphData = useCallback(
    async ({ silent = false } = {}) => {
      if (!isProjectHydratedForSelection) {
        return;
      }
      if (!graphId) {
        setGraphData(null);
        const message = "No graph data yet. Run Step B (Build Graph) for the selected project first.";
        setError(silent ? "" : message);
        setLoading(false);
        if (!silent) {
          addSystemLogRef.current?.(message);
        }
        return;
      }

      const requestScope = `${selectedProjectId}::${graphId}::${projectWorkspaceId}::${projectGraphBackend}`;
      // Prevent duplicate overlapping requests for the same scope.
      if (fetchInFlightRef.current && inFlightRequestScopeRef.current === requestScope) return;
      // Scope changed mid-flight (project switch): abort stale request and continue with new scope.
      if (fetchInFlightRef.current && inFlightRequestScopeRef.current !== requestScope) {
        try {
          fetchAbortControllerRef.current?.abort();
        } catch {
          // Best-effort cancellation only.
        }
      }
      const controller = new AbortController();
      fetchAbortControllerRef.current = controller;
      inFlightRequestScopeRef.current = requestScope;
      const requestSerial = fetchRequestSerialRef.current + 1;
      fetchRequestSerialRef.current = requestSerial;
      fetchInFlightRef.current = true;

      if (!silent) setLoading(true);
      if (!silent) setError("");

      try {
        const response = await trackedFetch(
          withApiBase(
            buildGraphDataApiPath(
              graphId,
              projectWorkspaceId,
              projectGraphBackend,
              selectedProjectId,
            ),
          ),
          {
            cache: "no-store",
            headers: { Accept: "application/json" },
            signal: controller.signal,
          },
          { source: silent ? "graph_data_polling" : "api" },
        );
        const payload = await response.json();
        if (requestSerial !== fetchRequestSerialRef.current || controller.signal.aborted) {
          return;
        }
        if (!response.ok || !payload?.success) {
          throw new Error(payload?.error ?? "Failed to fetch graph data");
        }
        const nextGraphData = payload.data ?? null;
        GRAPH_DATA_CACHE.set(graphCacheKey, nextGraphData);
        setGraphData(nextGraphData);
        setError("");
        const nodeCount = payload?.data?.node_count ?? payload?.data?.nodes?.length ?? 0;
        const edgeCount = payload?.data?.edge_count ?? payload?.data?.edges?.length ?? 0;
        if (silent && graphTaskStatusRef.current === "running") {
          reportLiveGraphBuildCountsRef.current?.(nodeCount, edgeCount);
        }
        if (!silent) {
          addSystemLogRef.current?.(`Graph data refreshed: nodes=${nodeCount}, edges=${edgeCount}`);
        }
      } catch (fetchError) {
        if (controller.signal.aborted) {
          return;
        }
        if (requestSerial !== fetchRequestSerialRef.current) {
          return;
        }
        const message = String(fetchError);
        if (silent) {
          return;
        }
        setGraphData(null);
        setError(message);
        addSystemLogRef.current?.(`Graph data refresh failed: ${message}`);
      } finally {
        if (fetchAbortControllerRef.current === controller) {
          fetchAbortControllerRef.current = null;
        }
        if (requestSerial === fetchRequestSerialRef.current) {
        fetchInFlightRef.current = false;
          inFlightRequestScopeRef.current = "";
        if (!silent) setLoading(false);
        }
      }
    },
    [
      graphCacheKey,
      graphId,
      isLiveBuildDataRefreshEnabled,
      isProjectHydratedForSelection,
      projectGraphBackend,
      projectWorkspaceId,
      selectedProjectId,
      trackedFetch,
    ],
  );

  useEffect(() => {
    // Reset current panel view whenever project/graph selection changes.
    setSelectedItem(null);
    setMultiEdgeSelection(null);
    setMultiNodeSelection(null);
    setMultipleSelectionWindow(null);
    setMultipleNodeSelectionWindow(null);
    setSelectedEntityTypes(null);
    setSelectedEdgeTypes(null);
    setEntityTypeSearchText("");
    setEdgeTypeSearchText("");
    setGraphSearchText("");
    setGraphSearchScope("all");
    setGraphSearchResult(null);
    setGraphSearchOpen(false);
    setInspectorTab("entity");
    if (!isProjectHydratedForSelection || (!isLiveBuildDataRefreshEnabled && !graphId)) {
      setGraphData(null);
      setError("");
      setLoading(false);
      return;
    }

    if (GRAPH_DATA_CACHE.has(graphCacheKey) && state.graphTask.status !== "running") {
      if (skipGraphReloadAfterOntologyRef.current) {
        skipGraphReloadAfterOntologyRef.current = false;
      }
      setGraphData(GRAPH_DATA_CACHE.get(graphCacheKey) ?? null);
      setError("");
      setLoading(false);
      return;
    }

    if (skipGraphReloadAfterOntologyRef.current) {
      skipGraphReloadAfterOntologyRef.current = false;
      setLoading(false);
      return;
    }

    setGraphData(null);
    setError("");
    setLoading(false);
    fetchGraphData();
  }, [
    fetchGraphData,
    graphCacheKey,
    graphId,
    isLiveBuildDataRefreshEnabled,
    isProjectHydratedForSelection,
    state.graphTask.status,
  ]);

  useEffect(
    () => () => {
      try {
        fetchAbortControllerRef.current?.abort();
      } catch {
        // Ignore cleanup abort errors.
      }
    },
    [],
  );

  useEffect(() => {
    if (state.graphTask.status !== "running" || !refreshDataWhileBuild || !graphId) return undefined;

    const tick = () => {
      fetchGraphData({ silent: true });
    };
    tick();
    const timer = window.setInterval(tick, graphDataPollIntervalMs);
    return () => window.clearInterval(timer);
  }, [state.graphTask.status, refreshDataWhileBuild, graphId, graphDataPollIntervalMs, fetchGraphData]);

  useEffect(() => {
    // Auto-refresh only after a graph build finishes.
    const previousStatus = previousGraphTaskStatusRef.current;
    const currentStatus = state.graphTask.status;
    previousGraphTaskStatusRef.current = currentStatus;

    const completedBuild = previousStatus === "running" && currentStatus === "success";
    if (!completedBuild) return;
    fetchGraphData();
  }, [fetchGraphData, state.graphTask.status]);

  useEffect(() => {
    // Manual refresh trigger from "Refresh graph data" button.
    if (!state.iframeVersion) return;
    fetchGraphData();
  }, [fetchGraphData, state.iframeVersion]);

  useEffect(() => {
    if (multiEdgeSelection?.edges?.length) {
      const visibleEdges = multiEdgeSelection.edges.filter((selectedEdge) => {
        const selectedKey = getEdgeSelectionKey(selectedEdge);
        return filteredGraphData.edges.some((edge) => getEdgeSelectionKey(edge) === selectedKey);
      });

      if (visibleEdges.length !== multiEdgeSelection.edges.length) {
        if (visibleEdges.length > 1) {
          setMultiEdgeSelection((prev) => {
            if (!prev) return prev;
            return { ...prev, edges: visibleEdges };
          });
        } else if (visibleEdges.length === 1) {
          setMultiEdgeSelection(null);
          setSelectedItem({
            type: "edge",
            data: visibleEdges[0],
          });
        } else {
          setMultiEdgeSelection(null);
        }
      }
    }

    if (!selectedItem) return;
    if (selectedItem.type === "node") {
      const selectedNodeId = String(selectedItem.data?.uuid ?? "");
      const visible = filteredGraphData.nodes.some((node) => String(node.uuid) === selectedNodeId);
      if (!visible) {
        selectedNodeUuidRef.current = "";
        setSelectedItem(null);
      }
      return;
    }
    if (selectedItem.type === "edge") {
      const edgeData = selectedItem.data ?? {};
      const source = String(edgeData.source_node_uuid ?? edgeData.source_uuid ?? "").trim();
      const target = String(edgeData.target_node_uuid ?? edgeData.target_uuid ?? "").trim();
      const relation = getRelationLabel(edgeData);

      if (edgeData.isSelfLoopGroup) {
        const visibleSelfLoop = filteredGraphData.edges.some((edge) => {
          const edgeSource = String(edge?.source_node_uuid ?? "").trim();
          const edgeTarget = String(edge?.target_node_uuid ?? "").trim();
          return edgeSource === source && edgeTarget === source;
        });
        if (!visibleSelfLoop) {
          setSelectedItem(null);
        }
        return;
      }

      const visible = filteredGraphData.edges.some((edge) => {
        const edgeSource = String(edge?.source_node_uuid ?? "").trim();
        const edgeTarget = String(edge?.target_node_uuid ?? "").trim();
        const edgeUuid = String(edge?.uuid ?? "").trim();
        const selectedUuid = String(edgeData?.uuid ?? "").trim();

        if (selectedUuid && edgeUuid && selectedUuid === edgeUuid) {
          return true;
        }
        return (
          edgeSource === source &&
          edgeTarget === target &&
          getRelationLabel(edge) === relation
        );
      });
      if (!visible) {
        setSelectedItem(null);
      }
    }
  }, [filteredGraphData, multiEdgeSelection, selectedItem]);

  useEffect(() => {
    if (!multiNodeSelection?.nodes?.length) return;
    const visibleNodes = multiNodeSelection.nodes.filter((selectedNode) => {
      const selectedKey = getNodeSelectionKey(selectedNode);
      return filteredGraphData.nodes.some((node) => getNodeSelectionKey(node) === selectedKey);
    });
    if (visibleNodes.length === multiNodeSelection.nodes.length) return;
    if (visibleNodes.length < 2) {
      setMultiNodeSelection(null);
      setMultipleNodeSelectionWindow(null);
      return;
    }
    setMultiNodeSelection((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        nodes: visibleNodes,
        selectedNodeKey: getNodeSelectionKey(visibleNodes[0]),
      };
    });
    setMultipleNodeSelectionWindow((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        selectedNodeKey: getNodeSelectionKey(visibleNodes[0]),
      };
    });
  }, [filteredGraphData, multiNodeSelection]);

  const renderGraph = useCallback(() => {
    clearSelectionRef.current = () => {};
    highlightEdgeInGraphRef.current = () => {};
    highlightEdgesInGraphRef.current = () => {};
    highlightNodeInGraphRef.current = () => {};
    highlightNodesInGraphRef.current = () => {};
    if (!svgRef.current || !containerRef.current || !graphData) return;
    if (simulationRef.current) {
      simulationRef.current.stop();
    }

    const container = containerRef.current;
    const width = Math.max(container.clientWidth, 320);
    const height = Math.max(container.clientHeight, 320);
    const svg = d3.select(svgRef.current).attr("width", width).attr("height", height);
    svg.selectAll("*").remove();

    const rawNodes = filteredGraphData.nodes;
    const rawEdges = filteredGraphData.edges;
    if (!rawNodes.length) return;

    const nodeNameById = new Map(
      rawNodes.map((node) => [String(node.uuid), getNodeDisplayLabel(node, graphLabelInput)]),
    );
    const nodes = rawNodes.map((node) => ({
      id: String(node.uuid),
      name: getNodeDisplayLabel(node, graphLabelInput),
      entityType: getEntityType(node),
      rawData: node,
    }));
    const nodeIds = new Set(nodes.map((node) => node.id));

    const pairCounts = new Map();
    const selfLoopByNode = new Map();

    rawEdges.forEach((edge) => {
      const source = String(edge?.source_node_uuid ?? "");
      const target = String(edge?.target_node_uuid ?? "");
      if (!nodeIds.has(source) || !nodeIds.has(target)) return;
      if (source === target) {
        const existing = selfLoopByNode.get(source) ?? [];
        existing.push({
          ...edge,
          source_name: nodeNameById.get(source) ?? "",
          target_name: nodeNameById.get(target) ?? "",
        });
        selfLoopByNode.set(source, existing);
        return;
      }
      const key = getEdgePairKey(source, target);
      pairCounts.set(key, (pairCounts.get(key) ?? 0) + 1);
    });

    const pairIndexes = new Map();
    const selfLoopProcessed = new Set();
    const links = [];

    rawEdges.forEach((edge) => {
      const source = String(edge?.source_node_uuid ?? "");
      const target = String(edge?.target_node_uuid ?? "");
      if (!nodeIds.has(source) || !nodeIds.has(target)) return;

      if (source === target) {
        if (selfLoopProcessed.has(source)) return;
        selfLoopProcessed.add(source);
        const loopEdges = selfLoopByNode.get(source) ?? [];
        links.push({
          source,
          target,
          name: appendGraphLabelSuffix(
            `Self Relations (${loopEdges.length})`,
            loopEdges[0] || {},
            graphLabelInput,
          ),
          isSelfLoop: true,
          curvature: 0,
          pairTotal: 1,
          rawData: {
            isSelfLoopGroup: true,
            source_uuid: source,
            target_uuid: target,
            source_name: nodeNameById.get(source) ?? "",
            target_name: nodeNameById.get(target) ?? "",
            selfLoopCount: loopEdges.length,
            selfLoopEdges: loopEdges,
          },
        });
        return;
      }

      const pairKey = getEdgePairKey(source, target);
      const pairTotal = pairCounts.get(pairKey) ?? 1;
      const pairIndex = pairIndexes.get(pairKey) ?? 0;
      pairIndexes.set(pairKey, pairIndex + 1);
      const normalizedDirectionFlip = source > target ? -1 : 1;
      const curvatureRange = Math.min(1.2, 0.6 + pairTotal * 0.15);
      const curvature =
        pairTotal > 1
          ? (((pairIndex / Math.max(pairTotal - 1, 1)) - 0.5) * curvatureRange * 2 * normalizedDirectionFlip)
          : 0;

      links.push({
        source,
        target,
        name: getEdgeDisplayLabel(edge, graphLabelInput),
        isSelfLoop: false,
        curvature,
        pairTotal,
        rawData: {
          ...edge,
          source_name: edge?.source_node_name || nodeNameById.get(source) || "",
          target_name: edge?.target_node_name || nodeNameById.get(target) || "",
        },
      });
    });

    const getTypeColor = (entityType) => typeToColor.get(entityType) ?? "#8f8f8f";

    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink(links)
          .id((node) => node.id)
          .distance((link) => {
            const pairTotal = Number(link.pairTotal ?? 1);
            return 140 + Math.max(pairTotal - 1, 0) * 45;
          }),
      )
      .force("charge", d3.forceManyBody().strength(-380))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide(36))
      .force("x", d3.forceX(width / 2).strength(0.04))
      .force("y", d3.forceY(height / 2).strength(0.04));

    simulationRef.current = simulation;

    const rootGroup = svg.append("g");
    svg.call(
      d3
        .zoom()
        .extent([
          [0, 0],
          [width, height],
        ])
        .scaleExtent([0.1, 4])
        .on("zoom", (event) => {
          rootGroup.attr("transform", event.transform);
        }),
    );

    const linkGroup = rootGroup.append("g").attr("class", "gv-links");
    const nodeGroup = rootGroup.append("g").attr("class", "gv-nodes");

    const computeLinkPath = (link) => {
      const sx = Number(link.source.x ?? 0);
      const sy = Number(link.source.y ?? 0);
      const tx = Number(link.target.x ?? 0);
      const ty = Number(link.target.y ?? 0);

      if (link.isSelfLoop) {
        const loopRadius = 30;
        return `M${sx + 8},${sy - 4} A${loopRadius},${loopRadius} 0 1,1 ${sx + 8},${sy + 4}`;
      }

      if (!link.curvature) {
        return `M${sx},${sy} L${tx},${ty}`;
      }

      const dx = tx - sx;
      const dy = ty - sy;
      const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const pairTotal = Number(link.pairTotal ?? 1);
      const offsetRatio = 0.25 + pairTotal * 0.05;
      const baseOffset = Math.max(35, distance * offsetRatio);
      const offsetX = (-dy / distance) * link.curvature * baseOffset;
      const offsetY = (dx / distance) * link.curvature * baseOffset;
      const cx = (sx + tx) / 2 + offsetX;
      const cy = (sy + ty) / 2 + offsetY;
      return `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`;
    };

    const computeLabelPoint = (link) => {
      const sx = Number(link.source.x ?? 0);
      const sy = Number(link.source.y ?? 0);
      const tx = Number(link.target.x ?? 0);
      const ty = Number(link.target.y ?? 0);

      if (link.isSelfLoop) {
        return { x: sx + 70, y: sy };
      }

      if (!link.curvature) {
        return { x: (sx + tx) / 2, y: (sy + ty) / 2 };
      }

      const dx = tx - sx;
      const dy = ty - sy;
      const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const pairTotal = Number(link.pairTotal ?? 1);
      const offsetRatio = 0.25 + pairTotal * 0.05;
      const baseOffset = Math.max(35, distance * offsetRatio);
      const offsetX = (-dy / distance) * link.curvature * baseOffset;
      const offsetY = (dx / distance) * link.curvature * baseOffset;
      const cx = (sx + tx) / 2 + offsetX;
      const cy = (sy + ty) / 2 + offsetY;
      return {
        x: 0.25 * sx + 0.5 * cx + 0.25 * tx,
        y: 0.25 * sy + 0.5 * cy + 0.25 * ty,
      };
    };

    const clearSelectionStyles = (linkPaths, nodeCircles, linkLabelTexts, linkLabelBackgrounds) => {
      linkPaths.attr("stroke", "#bdbdbd").attr("stroke-width", 1.5);
      nodeCircles.attr("stroke", "#fff").attr("stroke-width", 2.5);
      linkLabelTexts.attr("fill", "#666");
      linkLabelBackgrounds.attr("fill", "rgba(255, 255, 255, 0.95)");
    };

    const edgeMatchesSelection = (link, edgeData) => {
      const selectedUuid = String(edgeData?.uuid ?? "").trim();
      const linkUuid = String(link?.rawData?.uuid ?? "").trim();
      if (selectedUuid && linkUuid) {
        return selectedUuid === linkUuid;
      }
      const source = String(edgeData?.source_node_uuid ?? edgeData?.source_uuid ?? "").trim();
      const target = String(edgeData?.target_node_uuid ?? edgeData?.target_uuid ?? "").trim();
      const relation = getRelationLabel(edgeData);
      const linkSource = String(link?.rawData?.source_node_uuid ?? link?.rawData?.source_uuid ?? "").trim();
      const linkTarget = String(link?.rawData?.target_node_uuid ?? link?.rawData?.target_uuid ?? "").trim();
      const linkRelation = getRelationLabel(link?.rawData);
      return source === linkSource && target === linkTarget && relation === linkRelation;
    };

    const applyEdgeSelectionFromData = (edgeData) => {
      if (!edgeData || edgeData?.isSelfLoopGroup) return false;
      let matchedLink = null;
      for (const link of links) {
        if (edgeMatchesSelection(link, edgeData)) {
          matchedLink = link;
          break;
        }
      }
      if (!matchedLink) return false;
      selectedNodeUuidRef.current = "";
      selectedNodeHighlightKeysRef.current = new Set();
      clearSelectionStyles(linkPaths, nodeCircles, linkLabelTexts, linkLabelBackgrounds);
      linkPaths
        .filter((candidate) => candidate === matchedLink)
        .attr("stroke", "#3498db")
        .attr("stroke-width", 3);
      linkLabelTexts.filter((candidate) => candidate === matchedLink).attr("fill", "#3498db");
      linkLabelBackgrounds
        .filter((candidate) => candidate === matchedLink)
        .attr("fill", "rgba(52, 152, 219, 0.1)");
      return true;
    };

    const applyEdgeSelectionFromDataList = (edgeDataList) => {
      const keys = new Set(
        (Array.isArray(edgeDataList) ? edgeDataList : [])
          .map((edge) => getEdgeSelectionKey(edge))
          .filter(Boolean),
      );
      if (!keys.size) return false;

      selectedNodeUuidRef.current = "";
      selectedNodeHighlightKeysRef.current = new Set();
      clearSelectionStyles(linkPaths, nodeCircles, linkLabelTexts, linkLabelBackgrounds);

      const isSelectedLink = (link) => keys.has(getEdgeSelectionKey(link?.rawData));
      linkPaths
        .filter((candidate) => isSelectedLink(candidate))
        .attr("stroke", "#3498db")
        .attr("stroke-width", 3);
      linkLabelTexts.filter((candidate) => isSelectedLink(candidate)).attr("fill", "#3498db");
      linkLabelBackgrounds
        .filter((candidate) => isSelectedLink(candidate))
        .attr("fill", "rgba(52, 152, 219, 0.1)");
      return true;
    };

    const applyNodeSelectionFromData = (nodeData) => {
      const targetKey = getNodeSelectionKey(nodeData);
      if (!targetKey) return false;
      const selectedNode = nodes.find((candidate) => getNodeSelectionKey(candidate.rawData) === targetKey);
      if (!selectedNode) return false;

      selectedNodeUuidRef.current = String(selectedNode.rawData?.uuid ?? "");
      selectedNodeHighlightKeysRef.current = new Set([targetKey]);
      clearSelectionStyles(linkPaths, nodeCircles, linkLabelTexts, linkLabelBackgrounds);
      nodeCircles
        .filter((candidate) => getNodeSelectionKey(candidate.rawData) === targetKey)
        .attr("stroke", "#E91E63")
        .attr("stroke-width", 4);
      linkPaths
        .filter((link) => link.source.id === selectedNode.id || link.target.id === selectedNode.id)
        .attr("stroke", "#E91E63")
        .attr("stroke-width", 2.5);
      return true;
    };

    const applyNodeSelectionFromDataList = (nodeDataList) => {
      const nodeKeys = new Set(
        (Array.isArray(nodeDataList) ? nodeDataList : [])
          .map((node) => getNodeSelectionKey(node))
          .filter(Boolean),
      );
      if (!nodeKeys.size) return false;

      selectedNodeUuidRef.current = "";
      selectedNodeHighlightKeysRef.current = nodeKeys;
      clearSelectionStyles(linkPaths, nodeCircles, linkLabelTexts, linkLabelBackgrounds);

      nodeCircles
        .filter((candidate) => nodeKeys.has(getNodeSelectionKey(candidate.rawData)))
        .attr("stroke", "#3498db")
        .attr("stroke-width", 3.5);
      const selectedNodeIds = new Set(
        nodes
          .filter((candidate) => nodeKeys.has(getNodeSelectionKey(candidate.rawData)))
          .map((candidate) => candidate.id),
      );
      linkPaths
        .filter((link) => selectedNodeIds.has(link.source.id) || selectedNodeIds.has(link.target.id))
        .attr("stroke", "#3498db")
        .attr("stroke-width", 2.2);
      return true;
    };

    highlightEdgeInGraphRef.current = applyEdgeSelectionFromData;
    highlightEdgesInGraphRef.current = applyEdgeSelectionFromDataList;
    highlightNodeInGraphRef.current = applyNodeSelectionFromData;
    highlightNodesInGraphRef.current = applyNodeSelectionFromDataList;

    const linkPaths = linkGroup
      .selectAll("path")
      .data(links)
      .enter()
      .append("path")
      .attr("fill", "none")
      .attr("stroke", "#bdbdbd")
      .attr("stroke-width", 1.5)
      .style("cursor", "pointer");

    const linkLabelBackgrounds = linkGroup
      .selectAll("rect")
      .data(links)
      .enter()
      .append("rect")
      .attr("fill", "rgba(255, 255, 255, 0.95)")
      .attr("rx", 3)
      .attr("ry", 3)
      .style("display", showEdgeLabels ? "block" : "none")
      .style("cursor", "pointer");

    const linkLabelTexts = linkGroup
      .selectAll("text")
      .data(links)
      .enter()
      .append("text")
      .text((link) => String(link.name || "RELATED"))
      .attr("font-size", "9px")
      .attr("fill", "#666")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .style("font-family", "system-ui, sans-serif")
      .style("display", showEdgeLabels ? "block" : "none")
      .style("cursor", "pointer");

    const nodeCircles = nodeGroup
      .selectAll("circle")
      .data(nodes)
      .enter()
      .append("circle")
      .attr("r", 10)
      .attr("fill", (node) => getTypeColor(node.entityType))
      .attr("stroke", "#fff")
      .attr("stroke-width", 2.5)
      .style("cursor", "pointer")
      .call(
        d3
          .drag()
          .on("start", (event, node) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            node.fx = node.x;
            node.fy = node.y;
          })
          .on("drag", (event, node) => {
            node.fx = event.x;
            node.fy = event.y;
          })
          .on("end", (event, node) => {
            if (!event.active) simulation.alphaTarget(0);
            node.fx = null;
            node.fy = null;
          }),
      );

    const nodeLabels = nodeGroup
      .selectAll("text")
      .data(nodes)
      .enter()
      .append("text")
      .text((node) => (node.name.length > 10 ? `${node.name.slice(0, 10)}...` : node.name))
      .attr("font-size", "11px")
      .attr("fill", "#333")
      .attr("font-weight", "500")
      .attr("dx", 14)
      .attr("dy", 4)
      .style("pointer-events", "none")
      .style("font-family", "system-ui, sans-serif");

    clearSelectionRef.current = () => {
      selectedNodeUuidRef.current = "";
      selectedNodeHighlightKeysRef.current = new Set();
      clearSelectionStyles(linkPaths, nodeCircles, linkLabelTexts, linkLabelBackgrounds);
      setPreferSingleEdgeHighlight(false);
      setFocusedWindowId(null);
      setSelectedItem(null);
      setMultiEdgeSelection(null);
      setMultipleSelectionWindow(null);
      setMultiNodeSelection(null);
      setMultipleNodeSelectionWindow(null);
    };

    const selectEdge = (link, highlightTarget, clickEvent) => {
      setPreferSingleEdgeHighlight(false);
      const edgeData = link?.rawData ?? {};
      if (edgeData?.isSelfLoopGroup) {
      selectedNodeUuidRef.current = "";
      setInspectorTab("edgeStats");
        setMultiEdgeSelection(null);
        setMultiNodeSelection(null);
        setMultipleNodeSelectionWindow(null);
        applyEdgeSelectionFromData(edgeData);
      highlightTarget?.attr("fill", "rgba(52, 152, 219, 0.1)");
      setSelectedItem({
        type: "edge",
          data: edgeData,
        });
        setMultipleSelectionWindow(null);
        return;
      }

      const currentMulti = multiEdgeSelectionRef.current;
      const currentSelected = selectedItemRef.current;
      const currentSingleEdge =
        currentSelected?.type === "edge" && !currentSelected?.data?.isSelfLoopGroup
          ? currentSelected.data
          : null;
      const allowMultiSelect = Boolean(clickEvent?.altKey);

      if (allowMultiSelect) {
        const multiSelectionCandidate = buildPairMultiSelectionCandidate({
          clickedEdge: edgeData,
          currentMultiSelection: currentMulti,
          currentSingleEdge,
        });
        if (multiSelectionCandidate) {
          selectedNodeUuidRef.current = "";
          setInspectorTab("edgeStats");
          setSelectedItem(null);
          setMultiNodeSelection(null);
          setMultipleNodeSelectionWindow(null);
          // Alt multi-select enters pair-selection mode and clears any open edge-stat popup window.
          setEdgeStatsWindowsByBucket({});
          setMultiEdgeSelection({
            pairKey: multiSelectionCandidate.pairKey,
            edges: multiSelectionCandidate.edges,
          });
          setFocusedWindowId("multipleSelection");
          applyEdgeSelectionFromDataList(multiSelectionCandidate.edges);
          setMultipleSelectionWindow((prev) => {
            if (prev) {
              if (prev.selectedEdgeKey === multiSelectionCandidate.selectedEdgeKey) return prev;
              return { ...prev, selectedEdgeKey: multiSelectionCandidate.selectedEdgeKey };
            }
            return {
              bucket: "multipleSelection",
              x: lastMultipleSelectionWindowRef.current.x,
              y: lastMultipleSelectionWindowRef.current.y,
              width: lastMultipleSelectionWindowRef.current.width,
              selectedEdgeKey: multiSelectionCandidate.selectedEdgeKey,
            };
          });
          return;
        }
      }

      selectedNodeUuidRef.current = "";
      setInspectorTab("edgeStats");
      setMultiEdgeSelection(null);
      setMultiNodeSelection(null);
      setMultipleNodeSelectionWindow(null);
      setFocusedWindowId(null);
      setMultipleSelectionWindow(null);
      applyEdgeSelectionFromData(edgeData);
      highlightTarget?.attr("fill", "rgba(52, 152, 219, 0.1)");
      setSelectedItem({
        type: "edge",
        data: edgeData,
      });
    };

    const selectNode = (node, clickEvent) => {
      setPreferSingleEdgeHighlight(false);
      const nodeData = node?.rawData ?? null;
      const allowMultiSelect = Boolean(clickEvent?.altKey);
      const currentMulti = multiNodeSelectionRef.current;
      const currentSelected = selectedItemRef.current;
      const currentSingleNode = currentSelected?.type === "node" ? currentSelected.data : null;

      if (allowMultiSelect) {
        const multiSelectionCandidate = buildNodeMultiSelectionCandidate({
          clickedNode: nodeData,
          currentMultiSelection: currentMulti,
          currentSingleNode,
        });
        if (multiSelectionCandidate) {
          setInspectorTab("entity");
          setSelectedItem(null);
          setMultiEdgeSelection(null);
          setMultipleSelectionWindow(null);
          setMultiNodeSelection({
            selectedNodeKey: multiSelectionCandidate.selectedNodeKey,
            nodes: multiSelectionCandidate.nodes,
          });
          setFocusedWindowId(MULTIPLE_NODE_SELECTION_WINDOW_ID);
          applyNodeSelectionFromDataList(multiSelectionCandidate.nodes);
          setMultipleNodeSelectionWindow((prev) => {
            if (prev) {
              if (prev.selectedNodeKey === multiSelectionCandidate.selectedNodeKey) return prev;
              return { ...prev, selectedNodeKey: multiSelectionCandidate.selectedNodeKey };
            }
            return {
              bucket: MULTIPLE_NODE_SELECTION_WINDOW_ID,
              x: lastMultipleNodeSelectionWindowRef.current.x,
              y: lastMultipleNodeSelectionWindowRef.current.y,
              width: lastMultipleNodeSelectionWindowRef.current.width,
              selectedNodeKey: multiSelectionCandidate.selectedNodeKey,
            };
          });
          return;
        }
      }

      setMultiNodeSelection(null);
      setMultipleNodeSelectionWindow(null);
      setMultiEdgeSelection(null);
      setFocusedWindowId(null);
      setMultipleSelectionWindow(null);
      applyNodeSelectionFromData(nodeData);
      setSelectedItem({
        type: "node",
        data: nodeData,
        entityType: node.entityType,
        color: getTypeColor(node.entityType),
      });
    };

    linkPaths.on("click", function handleClick(event, link) {
      event.stopPropagation();
      selectEdge(link, null, event);
    });

    linkLabelTexts.on("click", function handleClick(event, link) {
      event.stopPropagation();
      selectEdge(link, null, event);
      d3.select(this).attr("fill", "#3498db");
    });

    linkLabelBackgrounds.on("click", function handleClick(event, link) {
      event.stopPropagation();
      selectEdge(link, d3.select(this), event);
    });

    nodeCircles
      .on("click", function handleClick(event, node) {
        event.stopPropagation();
        selectNode(node, event);
      })
      .on("mouseenter", function handleEnter() {
        d3.select(this).attr("stroke", "#333").attr("stroke-width", 3);
      })
      .on("mouseleave", function handleLeave(event, node) {
        const nodeKey = getNodeSelectionKey(node.rawData);
        if (selectedNodeHighlightKeysRef.current.has(nodeKey)) {
          const isSingleNodeSelection =
            selectedNodeUuidRef.current &&
            selectedNodeUuidRef.current === String(node.rawData.uuid ?? "");
          d3.select(this)
            .attr("stroke", isSingleNodeSelection ? "#E91E63" : "#3498db")
            .attr("stroke-width", isSingleNodeSelection ? 4 : 3.5);
          return;
        }
        d3.select(this).attr("stroke", "#fff").attr("stroke-width", 2.5);
      });

    simulation.on("tick", () => {
      linkPaths.attr("d", (link) => computeLinkPath(link));

      linkLabelTexts.each(function updateLabel(link) {
        const point = computeLabelPoint(link);
        d3.select(this).attr("x", point.x).attr("y", point.y);
      });

      linkLabelBackgrounds.each(function updateBackground(link, index) {
        const point = computeLabelPoint(link);
        const textNode = linkLabelTexts.nodes()[index];
        if (!textNode) return;
        const bbox = textNode.getBBox();
        d3.select(this)
          .attr("x", point.x - bbox.width / 2 - 4)
          .attr("y", point.y - bbox.height / 2 - 2)
          .attr("width", bbox.width + 8)
          .attr("height", bbox.height + 4);
      });

      nodeCircles.attr("cx", (node) => node.x).attr("cy", (node) => node.y);
      nodeLabels.attr("x", (node) => node.x).attr("y", (node) => node.y);
    });

    svg.on("click", (event) => {
      // Keep panel selections persistent when clicking empty canvas.
      // Selection can be cleared only via explicit close controls / Escape.
      if (event?.target !== svgRef.current) return;
    });
  }, [filteredGraphData, showEdgeLabels, typeToColor, graphLabelInput]);

  useEffect(() => {
    renderGraph();
    window.addEventListener("resize", renderGraph);
    return () => {
      window.removeEventListener("resize", renderGraph);
      if (simulationRef.current) {
        simulationRef.current.stop();
      }
    };
  }, [renderGraph]);

  useEffect(() => {
    if (selectedItem?.type === "edge") {
      if (selectedItem?.data?.isSelfLoopGroup) return;
      highlightEdgeInGraphRef.current(selectedItem.data);
      return;
    }
    if (selectedItem?.type === "node") {
      highlightNodeInGraphRef.current(selectedItem.data);
      return;
    }
    if (multiNodeSelection?.nodes?.length > 1) {
      highlightNodesInGraphRef.current(multiNodeSelection.nodes);
      return;
    }
    if (multiEdgeSelection?.edges?.length > 1 && !preferSingleEdgeHighlight) {
      highlightEdgesInGraphRef.current(multiEdgeSelection.edges);
      return;
    }
  }, [multiEdgeSelection, multiNodeSelection, preferSingleEdgeHighlight, selectedItem]);

  const closeDetail = () => {
    clearSelectionRef.current();
  };
  const beginDragDetailPanel = useCallback(
    (event) => {
      if (!selectedItem) return;
      if (event.button !== 0) return;
      if (event.target?.closest?.("button")) return;

      const panelElement = detailPanelRef.current;
      const containerElement = containerRef.current;
      if (!panelElement || !containerElement) return;

      event.preventDefault();

      const panelRect = panelElement.getBoundingClientRect();
      const containerRect = containerElement.getBoundingClientRect();
      detailPanelDragRef.current = {
        offsetX: event.clientX - panelRect.left,
        offsetY: event.clientY - panelRect.top,
        panelWidth: panelRect.width,
        panelHeight: panelRect.height,
        containerLeft: containerRect.left,
        containerTop: containerRect.top,
      };

      const onMouseMove = (moveEvent) => {
        const drag = detailPanelDragRef.current;
        if (!drag) return;
        const currentContainerRect = containerElement.getBoundingClientRect();
        const maxX = Math.max(0, currentContainerRect.width - drag.panelWidth);
        const maxY = Math.max(0, currentContainerRect.height - drag.panelHeight);
        const nextX = Math.min(
          maxX,
          Math.max(0, moveEvent.clientX - currentContainerRect.left - drag.offsetX),
        );
        const nextY = Math.min(
          maxY,
          Math.max(0, moveEvent.clientY - currentContainerRect.top - drag.offsetY),
        );
        setDetailPanelPosition((prev) => {
          if (prev && prev.x === nextX && prev.y === nextY) return prev;
          return { x: nextX, y: nextY };
        });
        const nextSide = isPanelDockedRightByMidpoint(
          nextX,
          drag.panelWidth,
          currentContainerRect.width,
        )
          ? "right"
          : "left";
        setDetailPanelSide((prev) => (prev === nextSide ? prev : nextSide));
      };

      const onMouseUp = () => {
        detailPanelDragRef.current = null;
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
      };

      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    },
    [selectedItem],
  );

  const toggleDetailPanelSide = useCallback(() => {
    const nextSide = detailPanelSide === "right" ? "left" : "right";
    setDetailPanelSide(nextSide);

    const panelElement = detailPanelRef.current;
    const containerElement = containerRef.current;
    if (!panelElement || !containerElement) return;

    const panelRect = panelElement.getBoundingClientRect();
    const containerRect = containerElement.getBoundingClientRect();
    const panelWidth = Math.max(0, panelRect.width);
    const panelHeight = Math.max(0, panelRect.height);
    const sideMargin = 16;
    const currentY =
      detailPanelPosition?.y ??
      Math.max(0, Math.round(panelRect.top - containerRect.top));
    const maxY = Math.max(0, containerRect.height - panelHeight);
    const nextY = Math.min(maxY, Math.max(0, currentY));
    const maxX = Math.max(0, containerRect.width - panelWidth);
    const nextX =
      nextSide === "left"
        ? Math.min(maxX, sideMargin)
        : Math.max(0, containerRect.width - panelWidth - sideMargin);

    setDetailPanelPosition({ x: nextX, y: nextY });
  }, [detailPanelPosition, detailPanelSide]);
  const detailPanelStyle = useMemo(() => {
    if (!detailPanelPosition) return undefined;
    return {
      left: detailPanelPosition.x,
      top: detailPanelPosition.y,
    };
  }, [detailPanelPosition]);
  const handleSelectAllEntityTypes = () => {
    setSelectedEntityTypes(null);
  };
  const handleClearEntityTypes = () => {
    setSelectedEntityTypes([]);
  };
  const toggleEntityType = (typeName) => {
    const allTypeNames = entityTypes.map((type) => type.name);
    setSelectedEntityTypes((prev) => {
      const current = prev === null ? [...allTypeNames] : [...prev];
      const currentSet = new Set(current);
      if (currentSet.has(typeName)) {
        currentSet.delete(typeName);
      } else {
        currentSet.add(typeName);
      }
      return Array.from(currentSet);
    });
  };
  const handleSelectAllEdgeTypes = () => {
    setSelectedEdgeTypes(null);
  };
  const handleClearEdgeTypes = () => {
    setSelectedEdgeTypes([]);
  };
  const toggleEdgeType = (typeName) => {
    const allTypeNames = edgeTypeOptions.map((type) => type.name);
    setSelectedEdgeTypes((prev) => {
      const current = prev === null ? [...allTypeNames] : [...prev];
      const currentSet = new Set(current);
      if (currentSet.has(typeName)) {
        currentSet.delete(typeName);
      } else {
        currentSet.add(typeName);
      }
      return Array.from(currentSet);
    });
  };
  const selectedTypeCount =
    selectedEntityTypes === null ? entityTypes.length : selectedEntityTypes.length;
  const allTypesSelected = selectedTypeCount === entityTypes.length && entityTypes.length > 0;
  const selectedEdgeTypeCount =
    selectedEdgeTypes === null ? edgeTypeOptions.length : selectedEdgeTypes.length;
  const allEdgeTypesSelected =
    selectedEdgeTypeCount === edgeTypeOptions.length && edgeTypeOptions.length > 0;
  const applyGraphSearchResult = useCallback(
    (option) => {
      if (!option) return;
      setGraphSearchResult(option);
      setGraphSearchText(option.label);
      setGraphSearchOpen(false);
      setMultiEdgeSelection(null);
      setMultiNodeSelection(null);
      setMultipleSelectionWindow(null);
      setMultipleNodeSelectionWindow(null);

      if (option.kind === "edge" && option.edgeData) {
        setInspectorTab("edgeStats");
        setPreferSingleEdgeHighlight(true);
        setSelectedItem({
          type: "edge",
          data: option.edgeData,
        });
        highlightEdgeInGraphRef.current(option.edgeData);
        return;
      }
      if (option.kind === "node" && option.nodeData) {
        const entityType = getEntityType(option.nodeData);
        setInspectorTab("entity");
        setPreferSingleEdgeHighlight(false);
        setSelectedItem({
          type: "node",
          data: option.nodeData,
          entityType,
          color: typeToColor.get(entityType) ?? "#8f8f8f",
        });
        highlightNodeInGraphRef.current(option.nodeData);
        return;
      }

      setInspectorTab("entity");
      setPreferSingleEdgeHighlight(false);
      setSelectedItem(null);
    },
    [typeToColor],
  );
  const totalNodeCount = graphData?.node_count ?? graphData?.nodes?.length ?? 0;
  const totalEdgeCount = graphData?.edge_count ?? graphData?.edges?.length ?? 0;
  const totalEpisodeCount = useMemo(() => {
    const edges = Array.isArray(graphData?.edges) ? graphData.edges : [];
    const ids = new Set();
    edges.forEach((edge) => {
      const episodes = Array.isArray(edge?.episodes) ? edge.episodes : [];
      episodes.forEach((episodeId) => {
        const normalized = String(episodeId ?? "").trim();
        if (normalized) ids.add(normalized);
      });
    });
    return ids.size;
  }, [graphData]);
  const filteredEpisodeCount = useMemo(() => {
    const edges = Array.isArray(filteredGraphData?.edges) ? filteredGraphData.edges : [];
    const ids = new Set();
    edges.forEach((edge) => {
      const episodes = Array.isArray(edge?.episodes) ? edge.episodes : [];
      episodes.forEach((episodeId) => {
        const normalized = String(episodeId ?? "").trim();
        if (normalized) ids.add(normalized);
      });
    });
    return ids.size;
  }, [filteredGraphData]);
  const selectedEdgeEpisodeIds = useMemo(() => {
    if (selectedItem?.type !== "edge") return [];
    const episodes = Array.isArray(selectedItem?.data?.episodes) ? selectedItem.data.episodes : [];
    const deduped = new Set();
    episodes.forEach((episodeId) => {
      const normalized = String(episodeId ?? "").trim();
      if (normalized) deduped.add(normalized);
    });
    return Array.from(deduped);
  }, [selectedItem]);
  const selectedEdgeStats = useMemo(() => {
    if (selectedItem?.type !== "edge") return null;
    return buildEdgeStatsForEdge(selectedItem.data ?? {}, graphData?.edges);
  }, [graphData, multiEdgeSelection, selectedItem]);

  const edgeStatsBuckets = useMemo(() => {
    if (!selectedEdgeStats) return null;
    return {
      sameRelationPair: {
        title: "Similar (Pair)",
        edges: selectedEdgeStats.sameRelationPairEdges,
      },
      sameRelationDirected: {
        title: "Similar (Direction)",
        edges: selectedEdgeStats.sameRelationDirectedEdges,
      },
      sameUndirectedPair: {
        title: "Parallel (Pair)",
        edges: selectedEdgeStats.sameUndirectedPairEdges,
      },
      sameRelationGlobal: {
        title: "Relation (Graph)",
        edges: selectedEdgeStats.sameRelationGlobalEdges,
      },
    };
  }, [selectedEdgeStats]);

  const activeEdgeStatsWindowsByBucket = useMemo(() => {
    const next = {};
    EDGE_STATS_BUCKETS.forEach((bucket) => {
      const windowState = edgeStatsWindowsByBucket?.[bucket];
      if (!windowState) return;
      const bucketData = edgeStatsBuckets?.[bucket] ?? null;
      const edges =
        bucketData && selectedEdgeStats
          ? Array.isArray(bucketData.edges)
            ? bucketData.edges
            : []
          : Array.isArray(windowState.edgesSnapshot)
            ? windowState.edgesSnapshot
            : [];
      const selectedEdgeKey = String(windowState.selectedEdgeKey ?? "").trim();
      const selectedEdge =
        edges.find((edge) => getEdgeSelectionKey(edge) === selectedEdgeKey) ?? null;
      next[bucket] = {
        title: bucketData?.title ?? windowState.titleSnapshot ?? bucket,
        relation: bucketData && selectedEdgeStats
          ? selectedEdgeStats.relation
          : windowState.relationSnapshot ?? "-",
        edges,
        selectedEdge,
      };
    });
    return next;
  }, [edgeStatsBuckets, edgeStatsWindowsByBucket, selectedEdgeStats]);

  const activeMultipleSelectionWindow = useMemo(() => {
    if (!multipleSelectionWindow) return null;
    const edges = Array.isArray(multiEdgeSelection?.edges) ? multiEdgeSelection.edges : [];
    if (!edges.length) return null;
    const first = edges[0] ?? {};
    const source = String(first?.source_node_name ?? first?.source_node_uuid ?? "-").trim();
    const target = String(first?.target_node_name ?? first?.target_node_uuid ?? "-").trim();
    const selectedEdgeKey = String(multipleSelectionWindow.selectedEdgeKey ?? "").trim();
    const selectedEdge = edges.find((edge) => getEdgeSelectionKey(edge) === selectedEdgeKey) ?? null;
    return {
      title: "Selected Pair Edges",
      relation: `${source} <-> ${target}`,
      edges,
      selectedEdge,
    };
  }, [multiEdgeSelection, multipleSelectionWindow]);

  const activeMultipleNodeSelectionWindow = useMemo(() => {
    if (!multipleNodeSelectionWindow) return null;
    const nodes = Array.isArray(multiNodeSelection?.nodes) ? multiNodeSelection.nodes : [];
    if (!nodes.length) return null;
    const selectedNodeKey = String(multipleNodeSelectionWindow.selectedNodeKey ?? "").trim();
    const selectionResetKey = nodes
      .map((node) => getNodeSelectionKey(node))
      .filter(Boolean)
      .join("|");
    const selectedNode =
      nodes.find((node) => getNodeSelectionKey(node) === selectedNodeKey) ?? nodes[0] ?? null;
    const selectedEntityType = selectedNode ? getEntityType(selectedNode) : "-";
    const groupedEdges = buildGroupedNodeEdgeSections(nodes, graphData?.edges);
    const nodeOneLabel = groupedEdges.nodeOne
      ? getNodeDisplayLabel(groupedEdges.nodeOne, graphLabelInput)
      : "Node1";
    const nodeTwoLabel = groupedEdges.nodeTwo
      ? getNodeDisplayLabel(groupedEdges.nodeTwo, graphLabelInput)
      : "Node2";
    const groupedEdgeArrays = [
      ...(Array.isArray(groupedEdges.nodeOneOnlyEdges) ? groupedEdges.nodeOneOnlyEdges : []),
      ...(Array.isArray(groupedEdges.sharedEdges) ? groupedEdges.sharedEdges : []),
      ...(Array.isArray(groupedEdges.nodeTwoOnlyEdges) ? groupedEdges.nodeTwoOnlyEdges : []),
    ];
    const groupedEdgeKeySet = new Set(groupedEdgeArrays.map((edge) => getEdgeSelectionKey(edge)).filter(Boolean));
    const selectedEdgeKeyFromWindow = String(multipleNodeSelectionWindow.selectedEdgeKey ?? "").trim();
    const selectedEdgeKeyFromItem =
      selectedItem?.type === "edge" ? getEdgeSelectionKey(selectedItem.data) : "";
    const selectedEdgeKey = groupedEdgeKeySet.has(selectedEdgeKeyFromWindow)
      ? selectedEdgeKeyFromWindow
      : groupedEdgeKeySet.has(selectedEdgeKeyFromItem)
        ? selectedEdgeKeyFromItem
        : "";
    return {
      title: "Selected Nodes",
      relation: `Total selected: ${nodes.length}`,
      nodes,
      selectedNode,
      selectedEntityType,
      selectionResetKey,
      selectedEdgeKey,
      groupedEdges: {
        ...groupedEdges,
        nodeOneLabel,
        nodeTwoLabel,
        sharedLabel: `${nodeOneLabel} ${nodeTwoLabel}`,
      },
    };
  }, [graphData?.edges, multiNodeSelection, multipleNodeSelectionWindow, selectedItem]);

  const closeAllEdgeStatsPopups = useCallback(() => {
    clearSelectionRef.current();
    setSelectedItem(null);
    setMultiEdgeSelection(null);
    setMultipleSelectionWindow(null);
    setMultiNodeSelection(null);
    setMultipleNodeSelectionWindow(null);
    setEdgeStatsWindowsByBucket({});
    setFocusedWindowId(null);
  }, []);

  const closeEdgeStatsWindowById = useCallback((windowId) => {
    if (!windowId) return;
    setFocusedWindowId((prev) => (prev === windowId ? null : prev));
    if (windowId === "multipleSelection") {
      setMultipleSelectionWindow(null);
      return;
    }
    if (windowId === MULTIPLE_NODE_SELECTION_WINDOW_ID) {
      setMultipleNodeSelectionWindow(null);
      return;
    }
    patchBucketWindow(windowId, null);
  }, [patchBucketWindow]);

  const getWindowStateById = useCallback((windowId) => {
    if (windowId === "multipleSelection") return multipleSelectionWindow;
    if (windowId === MULTIPLE_NODE_SELECTION_WINDOW_ID) return multipleNodeSelectionWindow;
    return edgeStatsWindowsByBucket?.[windowId] ?? null;
  }, [edgeStatsWindowsByBucket, multipleNodeSelectionWindow, multipleSelectionWindow]);

  const patchWindowStateById = useCallback((windowId, updater) => {
    if (windowId === "multipleSelection") {
      setMultipleSelectionWindow((prev) => {
        const nextValue = typeof updater === "function" ? updater(prev) : updater;
        return nextValue ?? null;
      });
      return;
    }
    if (windowId === MULTIPLE_NODE_SELECTION_WINDOW_ID) {
      setMultipleNodeSelectionWindow((prev) => {
        const nextValue = typeof updater === "function" ? updater(prev) : updater;
        return nextValue ?? null;
      });
      return;
    }
    patchBucketWindow(windowId, updater);
  }, [patchBucketWindow]);

  const openEdgeStatsPopup = useCallback(
    (bucket) => {
      if (!selectedEdgeStats) return;
      if (!EDGE_STATS_BUCKETS.includes(bucket)) return;
      const nextSelectedKey = getEdgeSelectionKey(
        selectedItem?.type === "edge" ? selectedItem.data : selectedEdgeStats.sameRelationGlobalEdges[0],
      );
      const bucketData = edgeStatsBuckets?.[bucket];
      const snapshotEdges = Array.isArray(bucketData?.edges) ? bucketData.edges : [];
      const snapshotRelation = selectedEdgeStats.relation;
      const snapshotTitle = bucketData?.title ?? bucket;
      setEdgeStatsWindowsByBucket((prev) => {
        const prevWindow = prev?.[bucket] ?? null;
        const nextWindow = prevWindow
          ? {
              ...prevWindow,
              selectedEdgeKey: nextSelectedKey || prevWindow.selectedEdgeKey,
              edgesSnapshot: snapshotEdges,
              relationSnapshot: snapshotRelation,
              titleSnapshot: snapshotTitle,
            }
          : {
              bucket,
              x: 28,
              y: 72,
              width: EDGE_STATS_WINDOW_DEFAULT_WIDTH,
              selectedEdgeKey: nextSelectedKey,
              edgesSnapshot: snapshotEdges,
              relationSnapshot: snapshotRelation,
              titleSnapshot: snapshotTitle,
            };
        return { [bucket]: nextWindow };
      });
      setFocusedWindowId(bucket);
    },
    [edgeStatsBuckets, selectedEdgeStats, selectedItem],
  );

  const selectEdgeFromStatsWindow = useCallback((edge, windowId, clickEvent) => {
    const selectedKey = getEdgeSelectionKey(edge);
    const nextSelectedStats = buildEdgeStatsForEdge(edge, graphData?.edges);
    const allowMultiSelect = Boolean(clickEvent?.altKey);

    if (allowMultiSelect) {
      const currentMulti = multiEdgeSelectionRef.current;
      const currentSelected = selectedItemRef.current;
      const currentSingleEdge =
        currentSelected?.type === "edge" && !currentSelected?.data?.isSelfLoopGroup
          ? currentSelected.data
          : null;
      const multiSelectionCandidate = buildPairMultiSelectionCandidate({
        clickedEdge: edge,
        currentMultiSelection: currentMulti,
        currentSingleEdge,
      });
      if (multiSelectionCandidate) {
        setInspectorTab("edgeStats");
        setFocusedWindowId("multipleSelection");
        setPreferSingleEdgeHighlight(false);
        setSelectedItem(null);
        setMultiNodeSelection(null);
        setMultipleNodeSelectionWindow(null);
        setMultiEdgeSelection({
          pairKey: multiSelectionCandidate.pairKey,
          edges: multiSelectionCandidate.edges,
        });
        highlightEdgesInGraphRef.current(multiSelectionCandidate.edges);
        setMultipleSelectionWindow((prev) => {
          if (prev) {
            if (prev.selectedEdgeKey === multiSelectionCandidate.selectedEdgeKey) return prev;
            return {
              ...prev,
              selectedEdgeKey: multiSelectionCandidate.selectedEdgeKey,
            };
          }
          return {
            bucket: "multipleSelection",
            x: lastMultipleSelectionWindowRef.current.x,
            y: lastMultipleSelectionWindowRef.current.y,
            width: lastMultipleSelectionWindowRef.current.width,
            selectedEdgeKey: multiSelectionCandidate.selectedEdgeKey,
          };
        });
        if (windowId && EDGE_STATS_BUCKETS.includes(windowId)) {
          patchBucketWindow(windowId, (prev) => {
            if (!prev) return prev;
            if (prev.selectedEdgeKey === multiSelectionCandidate.selectedEdgeKey) return prev;
            return { ...prev, selectedEdgeKey: multiSelectionCandidate.selectedEdgeKey };
          });
        }
        return;
      }
    }

    setInspectorTab("edgeStats");
    const isFromMultipleSelection = windowId === "multipleSelection";
    setPreferSingleEdgeHighlight(true);
    setMultiNodeSelection(null);
    setMultipleNodeSelectionWindow(null);
    setSelectedItem({
      type: "edge",
      data: edge,
    });
    highlightEdgeInGraphRef.current(edge);

    if (isFromMultipleSelection) {
      setMultipleSelectionWindow((prev) => {
        if (!prev) return prev;
        if (prev.selectedEdgeKey === selectedKey) return prev;
        return { ...prev, selectedEdgeKey: selectedKey };
      });
    } else if (windowId && EDGE_STATS_BUCKETS.includes(windowId)) {
      patchBucketWindow(windowId, (prev) => {
        if (!prev) return prev;
        if (prev.selectedEdgeKey === selectedKey) return prev;
        return { ...prev, selectedEdgeKey: selectedKey };
      });
    }

    setEdgeStatsWindowsByBucket((prev) => {
      if (!prev || !Object.keys(prev).length) return prev;
      let changed = false;
      const next = { ...prev };
      const snapshotByBucket = nextSelectedStats
        ? {
            sameRelationPair: {
              title: "Similar (Pair)",
              edges: nextSelectedStats.sameRelationPairEdges,
              relation: nextSelectedStats.relation,
            },
            sameRelationDirected: {
              title: "Similar (Direction)",
              edges: nextSelectedStats.sameRelationDirectedEdges,
              relation: nextSelectedStats.relation,
            },
            sameUndirectedPair: {
              title: "Parallel (Pair)",
              edges: nextSelectedStats.sameUndirectedPairEdges,
              relation: nextSelectedStats.relation,
            },
            sameRelationGlobal: {
              title: "Relation (Graph)",
              edges: nextSelectedStats.sameRelationGlobalEdges,
              relation: nextSelectedStats.relation,
            },
          }
        : null;
      EDGE_STATS_BUCKETS.forEach((bucket) => {
        const windowState = prev[bucket];
        if (!windowState) return;
        const snapshot = snapshotByBucket?.[bucket] ?? null;
        const shouldUpdateSelection = windowState.selectedEdgeKey !== selectedKey;
        const shouldUpdateSnapshot = Boolean(snapshot);
        if (!shouldUpdateSelection && !shouldUpdateSnapshot) return;
        next[bucket] = {
          ...windowState,
          selectedEdgeKey: shouldUpdateSelection ? selectedKey : windowState.selectedEdgeKey,
          edgesSnapshot: shouldUpdateSnapshot ? snapshot.edges : windowState.edgesSnapshot,
          relationSnapshot: shouldUpdateSnapshot ? snapshot.relation : windowState.relationSnapshot,
          titleSnapshot: shouldUpdateSnapshot ? snapshot.title : windowState.titleSnapshot,
        };
        changed = true;
      });
      return changed ? next : prev;
    });
  }, [graphData?.edges, patchBucketWindow]);

  const selectNodeFromStatsWindow = useCallback((node, windowId) => {
    const selectedNodeKey = getNodeSelectionKey(node);
    if (!selectedNodeKey) return;
    setInspectorTab("entity");
    setPreferSingleEdgeHighlight(false);
    setSelectedItem({
      type: "node",
      data: node,
      entityType: getEntityType(node),
      color: typeToColor.get(getEntityType(node)) ?? "#8f8f8f",
    });
    highlightNodeInGraphRef.current(node);
    if (windowId === MULTIPLE_NODE_SELECTION_WINDOW_ID) {
      setMultipleNodeSelectionWindow((prev) => {
        if (!prev) return prev;
        if (prev.selectedNodeKey === selectedNodeKey && !prev.selectedEdgeKey) return prev;
        return { ...prev, selectedNodeKey: selectedNodeKey, selectedEdgeKey: "" };
      });
      setMultiNodeSelection((prev) => {
        if (!prev) return prev;
        if (prev.selectedNodeKey === selectedNodeKey) return prev;
        return { ...prev, selectedNodeKey: selectedNodeKey };
      });
    }
  }, [typeToColor]);

  const selectEdgeFromNodeStatsWindow = useCallback((edge) => {
    const selectedEdgeKey = getEdgeSelectionKey(edge);
    setInspectorTab("edgeStats");
    setPreferSingleEdgeHighlight(true);
    setSelectedItem({
      type: "edge",
      data: edge,
    });
    highlightEdgeInGraphRef.current(edge);
    setMultipleNodeSelectionWindow((prev) => {
      if (!prev) return prev;
      if (prev.selectedEdgeKey === selectedEdgeKey) return prev;
      return { ...prev, selectedEdgeKey };
    });
  }, []);

  const handleSelectAllFromMultipleSelection = useCallback(() => {
    const edges = Array.isArray(multiEdgeSelection?.edges) ? multiEdgeSelection.edges : [];
    if (edges.length < 2) return;
    setFocusedWindowId("multipleSelection");
    setPreferSingleEdgeHighlight(false);
    highlightEdgesInGraphRef.current(edges);
  }, [multiEdgeSelection]);

  useEffect(() => {
    if (!multipleSelectionWindow) return;
    const multiEdges = Array.isArray(multiEdgeSelection?.edges) ? multiEdgeSelection.edges : [];
    if (multiEdges.length > 0) return;
    setFocusedWindowId((prev) => (prev === "multipleSelection" ? null : prev));
    setMultipleSelectionWindow(null);
  }, [multiEdgeSelection, multipleSelectionWindow]);

  useEffect(() => {
    if (!multipleNodeSelectionWindow) return;
    const multiNodes = Array.isArray(multiNodeSelection?.nodes) ? multiNodeSelection.nodes : [];
    if (multiNodes.length > 0) return;
    setFocusedWindowId((prev) =>
      prev === MULTIPLE_NODE_SELECTION_WINDOW_ID ? null : prev,
    );
    setMultipleNodeSelectionWindow(null);
  }, [multiNodeSelection, multipleNodeSelectionWindow]);

  const beginDragEdgeStatsWindow = useCallback(
    (event, windowId) => {
      const windowState = getWindowStateById(windowId);
      if (!windowState) return;
      if (event.button !== 0) return;
      event.preventDefault();
      const panelElement = getEdgeStatsWindowNode(windowId);
      const containerElement = containerRef.current;
      if (!panelElement || !containerElement) return;

      const panelRect = panelElement.getBoundingClientRect();
      const containerRect = containerElement.getBoundingClientRect();
      edgeStatsWindowDragRef.current = {
        windowId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        startX: windowState.x,
        startY: windowState.y,
        panelWidth: panelRect.width,
        panelHeight: panelRect.height,
        containerWidth: containerRect.width,
        containerHeight: containerRect.height,
      };

      const onMouseMove = (moveEvent) => {
        const drag = edgeStatsWindowDragRef.current;
        if (!drag) return;
        const deltaX = moveEvent.clientX - drag.startClientX;
        const deltaY = moveEvent.clientY - drag.startClientY;
        const maxX = Math.max(0, drag.containerWidth - drag.panelWidth);
        const maxY = Math.max(0, drag.containerHeight - drag.panelHeight);
        const nextX = Math.min(maxX, Math.max(0, drag.startX + deltaX));
        const nextY = Math.min(maxY, Math.max(0, drag.startY + deltaY));
        patchWindowStateById(drag.windowId, (prev) => {
          if (!prev) return prev;
          const shouldTrackDockSide = drag.windowId === "multipleSelection";
          const nextDockSide = shouldTrackDockSide
            ? isPanelDockedRightByMidpoint(nextX, drag.panelWidth, drag.containerWidth)
              ? "right"
              : "left"
            : prev.dockSide;
          if (prev.x === nextX && prev.y === nextY && prev.dockSide === nextDockSide) return prev;
          if (!shouldTrackDockSide) {
            return { ...prev, x: nextX, y: nextY };
          }
          return { ...prev, x: nextX, y: nextY, dockSide: nextDockSide };
        });
      };

      const onMouseUp = () => {
        edgeStatsWindowDragRef.current = null;
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
      };

      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    },
    [getEdgeStatsWindowNode, getWindowStateById, patchWindowStateById],
  );

  const beginResizeEdgeStatsWindow = useCallback(
    (event, windowId) => {
      const windowState = getWindowStateById(windowId);
      if (!windowState) return;
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();

      const panelElement = getEdgeStatsWindowNode(windowId);
      const containerElement = containerRef.current;
      if (!panelElement || !containerElement) return;

      const panelRect = panelElement.getBoundingClientRect();
      const containerRect = containerElement.getBoundingClientRect();
      const windowMinWidth =
        windowId === MULTIPLE_NODE_SELECTION_WINDOW_ID
          ? NODE_STATS_WINDOW_MIN_WIDTH
          : EDGE_STATS_WINDOW_MIN_WIDTH;
      const minWidth = Math.min(
        windowMinWidth,
        Math.max(280, containerRect.width - 12),
      );
      const startWidth =
        Number(windowState.width) > 0
          ? Number(windowState.width)
          : panelRect.width;

      edgeStatsWindowResizeRef.current = {
        windowId,
        startClientX: event.clientX,
        startWidth,
        startX: windowState.x,
        minWidth,
        containerWidth: containerRect.width,
      };

      const onMouseMove = (moveEvent) => {
        const resize = edgeStatsWindowResizeRef.current;
        if (!resize) return;
        const deltaX = moveEvent.clientX - resize.startClientX;
        const maxWidth = Math.max(resize.minWidth, resize.containerWidth - resize.startX);
        const nextWidth = Math.min(maxWidth, Math.max(resize.minWidth, resize.startWidth + deltaX));
        patchWindowStateById(resize.windowId, (prev) => {
          if (!prev) return prev;
          if (prev.width === nextWidth) return prev;
          return { ...prev, width: nextWidth };
        });
      };

      const onMouseUp = () => {
        edgeStatsWindowResizeRef.current = null;
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
      };

      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    },
    [getEdgeStatsWindowNode, getWindowStateById, patchWindowStateById],
  );

  const toggleEdgeStatsWindowSide = useCallback((windowId) => {
    const windowState = getWindowStateById(windowId);
    if (!windowState) return;
    const panelElement = getEdgeStatsWindowNode(windowId);
    const containerElement = containerRef.current;
    if (!panelElement || !containerElement) return;

    const panelRect = panelElement.getBoundingClientRect();
    const containerRect = containerElement.getBoundingClientRect();
    const currentWidth =
      Number(windowState.width) > 0 ? Number(windowState.width) : panelRect.width;
    const panelHeight = panelRect.height;
    const sideMargin = 16;
    const maxX = Math.max(0, containerRect.width - currentWidth);
    const maxY = Math.max(0, containerRect.height - panelHeight);
    const currentX = Math.min(maxX, Math.max(0, Number(windowState.x) || 0));
    const currentY = Math.min(maxY, Math.max(0, Number(windowState.y) || 0));
    const isDockedRight = isPanelDockedRightByMidpoint(
      currentX,
      currentWidth,
      containerRect.width,
    );
    const nextX = isDockedRight
      ? Math.min(maxX, sideMargin)
      : Math.max(0, containerRect.width - currentWidth - sideMargin);

    patchWindowStateById(windowId, (prev) => {
      if (!prev) return prev;
      if (windowId !== "multipleSelection") {
        return { ...prev, x: nextX, y: currentY };
      }
      return { ...prev, x: nextX, y: currentY, dockSide: isDockedRight ? "left" : "right" };
    });
  }, [getEdgeStatsWindowNode, getWindowStateById, patchWindowStateById]);

  const isEdgeStatsWindowDockedRight = useCallback((windowId) => {
    const windowState = getWindowStateById(windowId);
    if (!windowState) return false;
    if (windowId === "multipleSelection" && windowState.dockSide === "right") return true;
    if (windowId === "multipleSelection" && windowState.dockSide === "left") return false;
    const containerElement = containerRef.current;
    if (!containerElement) return false;
    const containerRect = containerElement.getBoundingClientRect();
    const width = Number(windowState.width) || EDGE_STATS_WINDOW_DEFAULT_WIDTH;
    const maxX = Math.max(0, containerRect.width - width);
    const currentX = Math.min(maxX, Math.max(0, Number(windowState.x) || 0));
    return isPanelDockedRightByMidpoint(currentX, width, containerRect.width);
  }, [getWindowStateById]);

  const toggleNodeStatsWindowSide = useCallback(() => {
    toggleEdgeStatsWindowSide(MULTIPLE_NODE_SELECTION_WINDOW_ID);
  }, [toggleEdgeStatsWindowSide]);

  const isNodeStatsWindowDockedRight = useMemo(
    () => isEdgeStatsWindowDockedRight(MULTIPLE_NODE_SELECTION_WINDOW_ID),
    [isEdgeStatsWindowDockedRight, multipleNodeSelectionWindow],
  );

  useEffect(() => {
    if (!selectedEdgeStats || !edgeStatsBuckets) return;
    const nextSelectedKey =
      selectedItem?.type === "edge" ? getEdgeSelectionKey(selectedItem.data) : "";
    setEdgeStatsWindowsByBucket((prev) => {
      if (!prev || !Object.keys(prev).length) return prev;
      let changed = false;
      const next = { ...prev };
      EDGE_STATS_BUCKETS.forEach((bucket) => {
        const windowState = prev[bucket];
        if (!windowState) return;
        const bucketData = edgeStatsBuckets[bucket];
        if (!bucketData) return;
        const nextEdges = Array.isArray(bucketData.edges) ? bucketData.edges : [];
        const nextTitle = bucketData.title;
        const shouldUpdateSelectedKey = Boolean(nextSelectedKey) && windowState.selectedEdgeKey !== nextSelectedKey;
        const sameEdges = windowState.edgesSnapshot === nextEdges;
        const sameRelation = windowState.relationSnapshot === selectedEdgeStats.relation;
        const sameTitle = windowState.titleSnapshot === nextTitle;
        if (!shouldUpdateSelectedKey && sameEdges && sameRelation && sameTitle) return;
        next[bucket] = {
          ...windowState,
          selectedEdgeKey: shouldUpdateSelectedKey ? nextSelectedKey : windowState.selectedEdgeKey,
          edgesSnapshot: nextEdges,
          relationSnapshot: selectedEdgeStats.relation,
          titleSnapshot: nextTitle,
        };
        changed = true;
      });
      return changed ? next : prev;
    });
  }, [edgeStatsBuckets, selectedEdgeStats, selectedItem]);

  useEffect(() => {
    const hasBucketWindows = Object.keys(edgeStatsWindowsByBucket ?? {}).length > 0;
    if (!hasBucketWindows && !multipleSelectionWindow && !multipleNodeSelectionWindow) return undefined;

    const ensureWindowInside = () => {
      const containerElement = containerRef.current;
      if (!containerElement) return;
      const containerRect = containerElement.getBoundingClientRect();

      const updateWindowBounds = (windowId) => {
        const panelElement = getEdgeStatsWindowNode(windowId);
        if (!panelElement) return;
        const panelRect = panelElement.getBoundingClientRect();
        const currentWindow = getWindowStateById(windowId);
        if (!currentWindow) return;
        const windowMinWidth =
          windowId === MULTIPLE_NODE_SELECTION_WINDOW_ID
            ? NODE_STATS_WINDOW_MIN_WIDTH
            : EDGE_STATS_WINDOW_MIN_WIDTH;
        const minWidth = Math.min(windowMinWidth, Math.max(280, containerRect.width - 12));
        const maxWidth = Math.max(minWidth, containerRect.width - 8);
        const currentWidth =
          Number(currentWindow.width) > 0 ? Number(currentWindow.width) : panelRect.width;
        const clampedWidth = Math.min(maxWidth, Math.max(minWidth, currentWidth));
        const maxX = Math.max(0, containerRect.width - clampedWidth);
        const maxY = Math.max(0, containerRect.height - panelRect.height);
        const clampedX = Math.min(maxX, Math.max(0, Number(currentWindow.x) || 0));
        const clampedY = Math.min(maxY, Math.max(0, Number(currentWindow.y) || 0));

        patchWindowStateById(windowId, (prev) => {
          if (!prev) return prev;
          if (prev.x === clampedX && prev.y === clampedY && prev.width === clampedWidth) return prev;
          return { ...prev, x: clampedX, y: clampedY, width: clampedWidth };
        });
      };

      EDGE_STATS_BUCKETS.forEach((bucket) => {
        if (!edgeStatsWindowsByBucket?.[bucket]) return;
        updateWindowBounds(bucket);
      });
      if (multipleSelectionWindow) {
        updateWindowBounds("multipleSelection");
      }
      if (multipleNodeSelectionWindow) {
        updateWindowBounds(MULTIPLE_NODE_SELECTION_WINDOW_ID);
      }
    };

    ensureWindowInside();
    window.addEventListener("resize", ensureWindowInside);
    return () => window.removeEventListener("resize", ensureWindowInside);
  }, [
    edgeStatsWindowsByBucket,
    getEdgeStatsWindowNode,
    getWindowStateById,
    multipleNodeSelectionWindow,
    multipleSelectionWindow,
    patchWindowStateById,
  ]);

  useEffect(() => {
    const hasBucketWindows = Object.keys(edgeStatsWindowsByBucket ?? {}).length > 0;
    if (!hasBucketWindows && !multipleSelectionWindow && !multipleNodeSelectionWindow) return undefined;

    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        const hasFocusedWindow = Boolean(focusedWindowId && getWindowStateById(focusedWindowId));
        if (hasFocusedWindow) {
          closeEdgeStatsWindowById(focusedWindowId);
          return;
        }
        closeAllEdgeStatsPopups();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    closeAllEdgeStatsPopups,
    closeEdgeStatsWindowById,
    edgeStatsWindowsByBucket,
    focusedWindowId,
    getWindowStateById,
    multipleNodeSelectionWindow,
    multipleSelectionWindow,
  ]);

  const renderState = () => {
    if (!graphId) {
      return (
        <div className="graph-state">
          <div className="graph-state-icon">◆</div>
          <p>Select a project and run graph build.</p>
        </div>
      );
    }
    if (loading) {
      return (
        <div className="graph-state">
          <div className="graph-loading-spinner" />
          <p>Loading graph data...</p>
        </div>
      );
    }
    if (error) {
      return (
        <div className="graph-state graph-state-error">
          <div className="graph-state-icon">!</div>
          <p>{error}</p>
        </div>
      );
    }
    if (!graphData?.nodes?.length) {
      return (
        <div className="graph-state">
          <div className="graph-state-icon">◌</div>
          <p>No nodes found yet.</p>
        </div>
      );
    }
    if (graphData?.nodes?.length && filteredGraphData.nodes.length === 0) {
      return (
        <div className="graph-state">
          <div className="graph-state-icon">◌</div>
          <p>No nodes match the active graph filters.</p>
        </div>
      );
    }
    return null;
  };

  return (
    <section className="left-panel">
      <div className="panel-header">
        <div className="panel-title">
          <span className="panel-icon">◆</span>
          Graph Relationship Visualization
          <button
            className={`graph-inspector-toggle ${inspectorOpen ? "active" : ""}`}
            type="button"
            onClick={() => setInspectorOpen((previous) => !previous)}
            disabled={!graphData?.nodes?.length}
            title={inspectorOpen ? "Hide filters and edge statistics panel" : "Show filters and edge statistics panel"}
          >
            {inspectorOpen ? "Hide Panel" : "Filters + Edge Stats"}
          </button>
        </div>
        <div className="graph-panel-actions">
          <span className="graph-panel-summary">
            nodes {filteredGraphData.nodes.length}/{totalNodeCount} | edges{" "}
            {filteredGraphData.edges.length}/{totalEdgeCount} | episodes{" "}
            {filteredEpisodeCount}/{totalEpisodeCount}
          </span>
          {showOpenInZepButton && (
          <button
            className="icon-btn"
            type="button"
            onClick={() => window.open(graphUrl, "_blank", "noopener,noreferrer")}
            title={canOpenZepGraph ? "Open graph in Zep" : "Build graph first (no graph link)"}
            disabled={!canOpenZepGraph}
          >
            ↗
          </button>
          )}
        <button
          className="icon-btn"
          type="button"
          onClick={refreshGraphFrame}
            title={graphId ? "Refresh graph data" : "Build graph first (no graph_id)"}
            disabled={loading || !graphId}
        >
          ↻
        </button>
      </div>
      </div>

      <div className="graph-canvas-wrap" ref={containerRef}>
        <svg ref={svgRef} className="graph-svg" />
        {renderState()}

        {graphData?.nodes?.length > 0 && inspectorOpen && (
            <GraphInspectorPanel
              inspectorTab={inspectorTab}
              setInspectorTab={setInspectorTab}
              handleSelectAllEntityTypes={handleSelectAllEntityTypes}
              allTypesSelected={allTypesSelected}
              handleClearEntityTypes={handleClearEntityTypes}
              selectedTypeCount={selectedTypeCount}
              entityTypeSearchText={entityTypeSearchText}
              setEntityTypeSearchText={setEntityTypeSearchText}
              visibleEntityTypeOptions={visibleEntityTypeOptions}
              activeEntityTypeSet={activeEntityTypeSet}
              toggleEntityType={toggleEntityType}
              handleSelectAllEdgeTypes={handleSelectAllEdgeTypes}
              allEdgeTypesSelected={allEdgeTypesSelected}
              handleClearEdgeTypes={handleClearEdgeTypes}
              selectedEdgeTypeCount={selectedEdgeTypeCount}
              edgeTypeSearchText={edgeTypeSearchText}
              setEdgeTypeSearchText={setEdgeTypeSearchText}
              visibleEdgeTypeOptions={visibleEdgeTypeOptions}
              activeEdgeTypeSet={activeEdgeTypeSet}
              toggleEdgeType={toggleEdgeType}
              selectedEdgeStats={selectedEdgeStats}
              selectedEdgeEpisodeIds={selectedEdgeEpisodeIds}
            onOpenEdgeStatsList={openEdgeStatsPopup}
            />
        )}

        {graphData?.nodes?.length > 0 && (
            <div className="graph-canvas-toolbar">
              <div className="graph-quick-search" ref={graphSearchContainerRef}>
                <div className="graph-quick-search-controls">
                  <input
                    className="graph-quick-search-input"
                    type="text"
                    value={graphSearchText}
                    onFocus={() => setGraphSearchOpen(Boolean(graphSearchText.trim()))}
                    onChange={(event) => {
                      const nextValue = event.target.value;
                      setGraphSearchText(nextValue);
                      setGraphSearchResult(null);
                      setGraphSearchOpen(Boolean(nextValue.trim()));
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") {
                        event.preventDefault();
                        setGraphSearchOpen(false);
                        return;
                      }
                      if (event.key === "Enter" && mergedGraphSearchOptions.length > 0) {
                        event.preventDefault();
                        applyGraphSearchResult(mergedGraphSearchOptions[0]);
                      }
                    }}
                    placeholder="Search graph"
                    aria-label="Search nodes, edges, and episodes"
                  />
                  {graphSearchText ? (
                    <button
                      className="graph-quick-search-clear"
                      type="button"
                      onClick={() => {
                        setGraphSearchText("");
                        setGraphSearchResult(null);
                        setGraphSearchOpen(false);
                      }}
                      title="Clear graph search"
                    >
                      ×
                    </button>
                  ) : null}
                  <select
                    className="graph-quick-search-scope"
                    value={graphSearchScope}
                    onChange={(event) => {
                      setGraphSearchScope(event.target.value);
                      setGraphSearchResult(null);
                      setGraphSearchOpen(Boolean(graphSearchText.trim()));
                    }}
                    aria-label="Filter search scope"
                  >
                    {GRAPH_SEARCH_SCOPES.map((scopeOption) => (
                      <option key={scopeOption.value} value={scopeOption.value}>
                        {scopeOption.label}
                      </option>
                    ))}
                  </select>
                </div>
                {graphSearchOpen &&
                (graphSearchOptions.length > 0 ||
                  backendGraphSearchOptions.length > 0 ||
                  isBackendGraphSearchLoading) ? (
                  <div className="graph-quick-search-results">
                    {graphSearchOptions.length > 0 ? (
                      <div className="graph-quick-search-section-title">Keyword filter</div>
                    ) : null}
                    {graphSearchOptions.map((option) => (
                      <button
                        key={option.key}
                        className={`graph-quick-search-option ${
                          graphSearchResult?.key === option.key ? "active" : ""
                        }`}
                        type="button"
                        onClick={() => applyGraphSearchResult(option)}
                      >
                        <span className="graph-quick-search-option-label">{option.label}</span>
                        <span className="graph-quick-search-option-subtitle">
                          {option.kind} - {option.subtitle}
                        </span>
                      </button>
                    ))}
                    {backendGraphSearchOptions.length > 0 ? (
                      <div className="graph-quick-search-section-title">Backend hybrid search</div>
                    ) : null}
                    {backendGraphSearchOptions.map((option) => (
                      <button
                        key={option.key}
                        className={`graph-quick-search-option graph-quick-search-option-remote ${
                          graphSearchResult?.key === option.key ? "active" : ""
                        }`}
                        type="button"
                        onClick={() => applyGraphSearchResult(option)}
                      >
                        <span className="graph-quick-search-option-label">{option.label}</span>
                        <span className="graph-quick-search-option-subtitle">
                          {option.kind} - {option.subtitle}
                        </span>
                      </button>
                    ))}
                    {isBackendGraphSearchLoading ? (
                      <div className="graph-quick-search-loading-row">Loading backend results...</div>
                    ) : null}
                  </div>
                ) : null}
              </div>
              <div className="graph-edge-label-toggle">
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={showEdgeLabels}
                    onChange={(event) => setShowEdgeLabels(event.target.checked)}
                  />
                  <span className="slider" />
                </label>
                <span className="toggle-label">Show Edge Labels</span>
              </div>
            </div>
        )}

        <GraphDetailPanel
          selectedItem={selectedItem}
          closeDetail={closeDetail}
          detailPanelSide={detailPanelSide}
          toggleDetailPanelSide={toggleDetailPanelSide}
          panelRef={detailPanelRef}
          panelStyle={detailPanelStyle}
          onBeginDrag={beginDragDetailPanel}
          isCustomPosition={Boolean(detailPanelPosition)}
          formatDateTime={formatDateTime}
          formatFieldValue={formatFieldValue}
          nodeEdgeStatsByNode={nodeEdgeStatsByNode}
          selectedEdgeEpisodeIds={selectedEdgeEpisodeIds}
        />

        {EDGE_STATS_BUCKETS.map((bucket) => {
          const windowState = edgeStatsWindowsByBucket?.[bucket];
          const activeWindow = activeEdgeStatsWindowsByBucket?.[bucket];
          if (!windowState || !activeWindow) return null;
          return (
            <EdgeStatsWindow
              key={bucket}
              panelRef={(node) => setEdgeStatsWindowNodeRef(bucket, node)}
              windowState={windowState}
              activeWindow={activeWindow}
              isFocused={focusedWindowId === bucket}
              onFocusWindow={() => setFocusedWindowId(bucket)}
              defaultWidth={EDGE_STATS_WINDOW_DEFAULT_WIDTH}
              onBeginDrag={(event) => beginDragEdgeStatsWindow(event, bucket)}
              onBeginResize={(event) => beginResizeEdgeStatsWindow(event, bucket)}
              onClose={() => closeEdgeStatsWindowById(bucket)}
              onSelectEdge={(edge, event) => selectEdgeFromStatsWindow(edge, bucket, event)}
              getEdgeSelectionKey={getEdgeSelectionKey}
            />
          );
        })}

        {multipleSelectionWindow && activeMultipleSelectionWindow && (
          <EdgeStatsWindow
            panelRef={(node) => setEdgeStatsWindowNodeRef("multipleSelection", node)}
            windowState={multipleSelectionWindow}
            activeWindow={activeMultipleSelectionWindow}
            isFocused={focusedWindowId === "multipleSelection"}
            onFocusWindow={() => setFocusedWindowId("multipleSelection")}
            defaultWidth={EDGE_STATS_WINDOW_DEFAULT_WIDTH}
            onBeginDrag={(event) => beginDragEdgeStatsWindow(event, "multipleSelection")}
            onBeginResize={(event) => beginResizeEdgeStatsWindow(event, "multipleSelection")}
            onToggleDock={() => toggleEdgeStatsWindowSide("multipleSelection")}
            isDockedRight={isEdgeStatsWindowDockedRight("multipleSelection")}
            onClose={() => closeEdgeStatsWindowById("multipleSelection")}
            onSelectEdge={(edge, event) =>
              selectEdgeFromStatsWindow(edge, "multipleSelection", event)
            }
            showSelectAll
            onSelectAll={handleSelectAllFromMultipleSelection}
            getEdgeSelectionKey={getEdgeSelectionKey}
          />
        )}

        {multipleNodeSelectionWindow && activeMultipleNodeSelectionWindow && (
          <NodeStatsWindow
            panelRef={(node) => setEdgeStatsWindowNodeRef(MULTIPLE_NODE_SELECTION_WINDOW_ID, node)}
            windowState={multipleNodeSelectionWindow}
            activeWindow={activeMultipleNodeSelectionWindow}
            isFocused={focusedWindowId === MULTIPLE_NODE_SELECTION_WINDOW_ID}
            onFocusWindow={() => setFocusedWindowId(MULTIPLE_NODE_SELECTION_WINDOW_ID)}
            defaultWidth={NODE_STATS_WINDOW_DEFAULT_WIDTH}
            onBeginDrag={(event) => beginDragEdgeStatsWindow(event, MULTIPLE_NODE_SELECTION_WINDOW_ID)}
            onBeginResize={(event) => beginResizeEdgeStatsWindow(event, MULTIPLE_NODE_SELECTION_WINDOW_ID)}
            onToggleDock={toggleNodeStatsWindowSide}
            isDockedRight={isNodeStatsWindowDockedRight}
            onClose={() => closeEdgeStatsWindowById(MULTIPLE_NODE_SELECTION_WINDOW_ID)}
            onSelectNode={(node) => selectNodeFromStatsWindow(node, MULTIPLE_NODE_SELECTION_WINDOW_ID)}
            onSelectEdge={selectEdgeFromNodeStatsWindow}
            getNodeSelectionKey={getNodeSelectionKey}
          />
        )}
      </div>
    </section>
  );
}
