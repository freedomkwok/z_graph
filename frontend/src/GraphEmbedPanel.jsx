import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import * as d3 from "d3";

import { useTaskStore } from "./taskStore";

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

function getGraphId(project) {
  return String(project?.zep_graph_id ?? project?.graph_id ?? project?.project_id ?? "").trim();
}

function getEntityType(node) {
  const labels = Array.isArray(node?.labels) ? node.labels : [];
  const custom = labels.find((label) => label !== "Entity" && label !== "Node");
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

function getEdgePairKey(sourceId, targetId) {
  return sourceId < targetId ? `${sourceId}_${targetId}` : `${targetId}_${sourceId}`;
}

function getRelationLabel(edge) {
  return String(edge?.name || edge?.fact_type || "RELATED").trim() || "RELATED";
}

function getDirectedEdgeKey(sourceId, targetId) {
  return `${String(sourceId ?? "").trim()}->${String(targetId ?? "").trim()}`;
}

function buildEntityTypeList(nodes) {
  const typeToColor = new Map();
  const types = [];

  nodes.forEach((node) => {
    const type = getEntityType(node);
    if (typeToColor.has(type)) return;
    const color = TYPE_COLORS[typeToColor.size % TYPE_COLORS.length];
    typeToColor.set(type, color);
    types.push({ name: type, color });
  });

  return { types, typeToColor };
}

export default function GraphEmbedPanel() {
  const { state, refreshGraphFrame, setViewMode, addSystemLog } = useTaskStore();
  const isGraphOnly = state.viewMode === "graph";
  const graphId = getGraphId(state.currentProject);
  const graphUrl = resolveGraphEmbedUrl(state.currentProject);

  const containerRef = useRef(null);
  const svgRef = useRef(null);
  const simulationRef = useRef(null);
  const selectedNodeUuidRef = useRef("");
  const clearSelectionRef = useRef(() => {});
  const addSystemLogRef = useRef(addSystemLog);
  const fetchInFlightRef = useRef(false);
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedItem, setSelectedItem] = useState(null);
  const [showEdgeLabels, setShowEdgeLabels] = useState(true);
  const [selectedEntityTypes, setSelectedEntityTypes] = useState(null);
  const [selectedEdgeTypes, setSelectedEdgeTypes] = useState(null);
  const [entityTypeSearchText, setEntityTypeSearchText] = useState("");
  const [edgeTypeSearchText, setEdgeTypeSearchText] = useState("");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorTab, setInspectorTab] = useState("entity");
  const projectUpdateToken = useMemo(() => {
    const project = state.currentProject;
    if (!project) return "";
    return [
      String(project.project_id ?? ""),
      String(project.updated_at ?? ""),
      String(project.status ?? ""),
      String(project.graph_build_task_id ?? ""),
      String(project.zep_graph_id ?? project.graph_id ?? ""),
    ].join("|");
  }, [state.currentProject]);

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
  const filteredGraphData = useMemo(() => {
    const nodes = Array.isArray(graphData?.nodes) ? graphData.nodes : [];
    const edges = Array.isArray(graphData?.edges) ? graphData.edges : [];
    if (!nodes.length) {
      return { nodes: [], edges: [] };
    }
    const filteredNodes = nodes.filter((node) => activeEntityTypeSet.has(getEntityType(node)));
    const visibleNodeIds = new Set(filteredNodes.map((node) => String(node.uuid)));
    const filteredEdges = edges.filter((edge) => {
      const source = String(edge?.source_node_uuid ?? "");
      const target = String(edge?.target_node_uuid ?? "");
      const relation = getRelationLabel(edge);
      return (
        visibleNodeIds.has(source) &&
        visibleNodeIds.has(target) &&
        activeEdgeTypeSet.has(relation)
      );
    });
    return { nodes: filteredNodes, edges: filteredEdges };
  }, [activeEdgeTypeSet, activeEntityTypeSet, graphData]);
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
      if (!graphId) {
        setGraphData(null);
        setError("");
        setLoading(false);
        return;
      }

      // Prevent overlapping requests when multiple effects trigger close together.
      if (fetchInFlightRef.current) return;
      fetchInFlightRef.current = true;

      if (!silent) setLoading(true);
      if (!silent) setError("");

      try {
        const response = await fetch(
          withApiBase(`/api/data/${encodeURIComponent(graphId)}?include_episode_data=false`),
          {
          cache: "no-store",
          headers: { Accept: "application/json" },
          },
        );
        const payload = await response.json();
        if (!response.ok || !payload?.success) {
          throw new Error(payload?.error ?? "Failed to fetch graph data");
        }
        setGraphData(payload.data ?? null);
        setError("");
        if (!silent) {
          const nodeCount = payload?.data?.node_count ?? payload?.data?.nodes?.length ?? 0;
          const edgeCount = payload?.data?.edge_count ?? payload?.data?.edges?.length ?? 0;
          addSystemLogRef.current?.(`Graph data refreshed: nodes=${nodeCount}, edges=${edgeCount}`);
        }
      } catch (fetchError) {
        const message = String(fetchError);
        setGraphData(null);
        setError(message);
        if (!silent) addSystemLogRef.current?.(`Graph data refresh failed: ${message}`);
      } finally {
        fetchInFlightRef.current = false;
        if (!silent) setLoading(false);
      }
    },
    [graphId],
  );

  useEffect(() => {
    setSelectedItem(null);
    setSelectedEntityTypes(null);
    setSelectedEdgeTypes(null);
    setEntityTypeSearchText("");
    setEdgeTypeSearchText("");
    setInspectorTab("entity");
    setInspectorOpen(false);
    fetchGraphData();
  }, [fetchGraphData, projectUpdateToken, state.iframeVersion]);

  useEffect(() => {
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
  }, [filteredGraphData, selectedItem]);

  const renderGraph = useCallback(() => {
    clearSelectionRef.current = () => {};
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

    const nodeNameById = new Map(rawNodes.map((node) => [String(node.uuid), node.name || "Unnamed"]));
    const nodes = rawNodes.map((node) => ({
      id: String(node.uuid),
      name: String(node.name || "Unnamed"),
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
          name: `Self Relations (${loopEdges.length})`,
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
        name: String(edge?.name || edge?.fact_type || "RELATED"),
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
      clearSelectionStyles(linkPaths, nodeCircles, linkLabelTexts, linkLabelBackgrounds);
      setSelectedItem(null);
    };

    const selectEdge = (link, highlightTarget) => {
      selectedNodeUuidRef.current = "";
      setInspectorTab("edgeStats");
      clearSelectionStyles(linkPaths, nodeCircles, linkLabelTexts, linkLabelBackgrounds);
      linkPaths.filter((candidate) => candidate === link).attr("stroke", "#3498db").attr("stroke-width", 3);
      highlightTarget?.attr("fill", "rgba(52, 152, 219, 0.1)");
      setSelectedItem({
        type: "edge",
        data: link.rawData,
      });
    };

    const selectNode = (node, target) => {
      selectedNodeUuidRef.current = String(node.rawData.uuid ?? "");
      clearSelectionStyles(linkPaths, nodeCircles, linkLabelTexts, linkLabelBackgrounds);
      target.attr("stroke", "#E91E63").attr("stroke-width", 4);
      linkPaths
        .filter((link) => link.source.id === node.id || link.target.id === node.id)
        .attr("stroke", "#E91E63")
        .attr("stroke-width", 2.5);
      setSelectedItem({
        type: "node",
        data: node.rawData,
        entityType: node.entityType,
        color: getTypeColor(node.entityType),
      });
    };

    linkPaths.on("click", function handleClick(event, link) {
      event.stopPropagation();
      selectEdge(link, null);
    });

    linkLabelTexts.on("click", function handleClick(event, link) {
      event.stopPropagation();
      selectEdge(link, null);
      d3.select(this).attr("fill", "#3498db");
    });

    linkLabelBackgrounds.on("click", function handleClick(event, link) {
      event.stopPropagation();
      selectEdge(link, d3.select(this));
    });

    nodeCircles
      .on("click", function handleClick(event, node) {
        event.stopPropagation();
        selectNode(node, d3.select(this));
      })
      .on("mouseenter", function handleEnter() {
        d3.select(this).attr("stroke", "#333").attr("stroke-width", 3);
      })
      .on("mouseleave", function handleLeave(event, node) {
        if (selectedNodeUuidRef.current && selectedNodeUuidRef.current === String(node.rawData.uuid ?? "")) {
          d3.select(this).attr("stroke", "#E91E63").attr("stroke-width", 4);
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

    svg.on("click", () => {
      clearSelectionRef.current();
    });
  }, [filteredGraphData, showEdgeLabels, typeToColor]);

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

  const closeDetail = () => {
    clearSelectionRef.current();
  };
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
    if (selectedItem?.data?.isSelfLoopGroup) return null;

    const selectedEdge = selectedItem.data ?? {};
    const selectedSource = String(selectedEdge.source_node_uuid ?? "").trim();
    const selectedTarget = String(selectedEdge.target_node_uuid ?? "").trim();
    const selectedRelation = getRelationLabel(selectedEdge);
    if (!selectedSource || !selectedTarget) return null;

    const selectedDirectedKey = getDirectedEdgeKey(selectedSource, selectedTarget);
    const selectedUndirectedKey = getEdgePairKey(selectedSource, selectedTarget);
    const edges = Array.isArray(graphData?.edges) ? graphData.edges : [];

    let sameUndirectedPairCount = 0;
    let sameRelationDirectedCount = 0;
    let sameRelationPairCount = 0;
    let sameRelationGlobalCount = 0;

    edges.forEach((edge) => {
      const source = String(edge?.source_node_uuid ?? "").trim();
      const target = String(edge?.target_node_uuid ?? "").trim();
      if (!source || !target) return;

      const relation = getRelationLabel(edge);
      const directedKey = getDirectedEdgeKey(source, target);
      const undirectedKey = getEdgePairKey(source, target);
      const isSameRelation = relation === selectedRelation;

      if (directedKey === selectedDirectedKey) {
        if (isSameRelation) {
          sameRelationDirectedCount += 1;
        }
      }

      if (undirectedKey === selectedUndirectedKey) {
        sameUndirectedPairCount += 1;
        if (isSameRelation) {
          sameRelationPairCount += 1;
        }
      }

      if (isSameRelation) {
        sameRelationGlobalCount += 1;
      }
    });

    return {
      relation: selectedRelation,
      sameUndirectedPairCount,
      sameRelationDirectedCount,
      sameRelationPairCount,
      sameRelationGlobalCount,
    };
  }, [graphData, selectedItem]);

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
          <p>No nodes match the selected entity type filter.</p>
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
          {isGraphOnly && (
            <button
              className="icon-btn"
              type="button"
              onClick={() => setViewMode("both")}
              title="Show backend and graph"
            >
              ◧
            </button>
          )}
          <button
            className="icon-btn"
            type="button"
            onClick={() => window.open(graphUrl, "_blank", "noopener,noreferrer")}
            title="Open graph in Zep"
            disabled={!graphId}
          >
            ↗
          </button>
          <button
            className="icon-btn"
            type="button"
            onClick={refreshGraphFrame}
            title="Refresh graph data"
            disabled={loading}
          >
            ↻
          </button>
        </div>
      </div>

      <div className="graph-canvas-wrap" ref={containerRef}>
        <svg ref={svgRef} className="graph-svg" />
        {renderState()}

        {graphData?.nodes?.length > 0 && inspectorOpen && (
          <>
            <div className="graph-legend graph-inspector-panel">
              <div className="graph-inspector-tabs">
                <button
                  className={`graph-inspector-tab ${inspectorTab === "entity" ? "active" : ""}`}
                  type="button"
                  onClick={() => setInspectorTab("entity")}
                >
                  Entity Types
                </button>
                <button
                  className={`graph-inspector-tab ${inspectorTab === "edgeList" ? "active" : ""}`}
                  type="button"
                  onClick={() => setInspectorTab("edgeList")}
                >
                  Edges
                </button>
                <button
                  className={`graph-inspector-tab ${inspectorTab === "edgeStats" ? "active" : ""}`}
                  type="button"
                  onClick={() => setInspectorTab("edgeStats")}
                >
                  Edge Statistics
                </button>
              </div>
              {inspectorTab === "entity" ? (
                <div className="entity-filter-panel">
                  <div className="entity-filter-head">
                    <span className="legend-title">Entity Types</span>
                    <div className="entity-filter-actions">
                      <button
                        className="entity-filter-btn"
                        type="button"
                        onClick={handleSelectAllEntityTypes}
                        disabled={allTypesSelected}
                      >
                        All
                      </button>
                      <button
                        className="entity-filter-btn"
                        type="button"
                        onClick={handleClearEntityTypes}
                        disabled={selectedTypeCount === 0}
                      >
                        Clear
                      </button>
                    </div>
                  </div>
                  <input
                    className="graph-inspector-search"
                    type="text"
                    value={entityTypeSearchText}
                    onChange={(event) => setEntityTypeSearchText(event.target.value)}
                    placeholder="Filter entity types..."
                  />
                  <div className="entity-filter-list">
                    {visibleEntityTypeOptions.length > 0 ? (
                      visibleEntityTypeOptions.map((type) => (
                        <label className="legend-item entity-filter-item" key={type.name}>
                          <input
                            className="entity-filter-checkbox"
                            type="checkbox"
                            checked={activeEntityTypeSet.has(type.name)}
                            onChange={() => toggleEntityType(type.name)}
                          />
                          <span className="legend-dot" style={{ background: type.color }} />
                          <span className="legend-label">{type.name}</span>
                        </label>
                      ))
                    ) : (
                      <div className="graph-inspector-empty">
                        No entity types match the filter text.
                      </div>
                    )}
                  </div>
                </div>
              ) : inspectorTab === "edgeList" ? (
                <div className="entity-filter-panel">
                  <div className="entity-filter-head">
                    <span className="legend-title">Edges</span>
                    <div className="entity-filter-actions">
                      <button
                        className="entity-filter-btn"
                        type="button"
                        onClick={handleSelectAllEdgeTypes}
                        disabled={allEdgeTypesSelected}
                      >
                        All
                      </button>
                      <button
                        className="entity-filter-btn"
                        type="button"
                        onClick={handleClearEdgeTypes}
                        disabled={selectedEdgeTypeCount === 0}
                      >
                        Clear
                      </button>
                    </div>
                  </div>
                  <input
                    className="graph-inspector-search"
                    type="text"
                    value={edgeTypeSearchText}
                    onChange={(event) => setEdgeTypeSearchText(event.target.value)}
                    placeholder="Filter edge types..."
                  />
                  <div className="entity-filter-list">
                    {visibleEdgeTypeOptions.length > 0 ? (
                      visibleEdgeTypeOptions.map((type) => (
                        <label className="legend-item entity-filter-item edge-filter-item" key={type.name}>
                          <input
                            className="entity-filter-checkbox"
                            type="checkbox"
                            checked={activeEdgeTypeSet.has(type.name)}
                            onChange={() => toggleEdgeType(type.name)}
                          />
                          <span className="legend-label edge-filter-label">{type.name}</span>
                          <span className="edge-filter-count">{type.count}</span>
                        </label>
                      ))
                    ) : (
                      <div className="graph-inspector-empty">No edges match the filter text.</div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="edge-stats-panel">
                  {selectedEdgeStats ? (
                    <>
                      <div className="edge-stats-relation-name">
                        Relation: {selectedEdgeStats.relation}
                      </div>
                      <div className="graph-detail-columns edge-stats-columns">
                        <div className="graph-detail-column">
                          <span className="graph-detail-column-label">Similar (Pair)</span>
                          <span className="graph-detail-column-value">
                            {selectedEdgeStats.sameRelationPairCount}
                          </span>
                        </div>
                        <div className="graph-detail-column">
                          <span className="graph-detail-column-label">Similar (Direction)</span>
                          <span className="graph-detail-column-value">
                            {selectedEdgeStats.sameRelationDirectedCount}
                          </span>
                        </div>
                        <div className="graph-detail-column">
                          <span className="graph-detail-column-label">Parallel (Pair)</span>
                          <span className="graph-detail-column-value">
                            {selectedEdgeStats.sameUndirectedPairCount}
                          </span>
                        </div>
                        <div className="graph-detail-column">
                          <span className="graph-detail-column-label">Relation (Graph)</span>
                          <span className="graph-detail-column-value">
                            {selectedEdgeStats.sameRelationGlobalCount}
                          </span>
                        </div>
                      </div>
                      <div className="edge-stats-episodes-total">
                        Episodes (Total: {selectedEdgeEpisodeIds.length})
                      </div>
                    </>
                  ) : (
                    <div className="graph-inspector-empty">
                      Select a relationship in the graph to view similar-edge statistics.
                    </div>
                  )}
                </div>
              )}
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
          </>
        )}

        {selectedItem && (
          <aside className="graph-detail-panel">
            <div className="graph-detail-head">
              <div className="graph-detail-title-wrap">
                <span className="graph-detail-title">
                  {selectedItem.type === "node" ? "Node Details" : "Relationship"}
                </span>
                {selectedItem.type === "node" && (
                  <span
                    className="graph-detail-type-badge"
                    style={{ background: selectedItem.color || "#8f8f8f" }}
                  >
                    {selectedItem.entityType || "Entity"}
                  </span>
                )}
              </div>
              <button className="graph-detail-close" type="button" onClick={closeDetail}>
                ×
              </button>
            </div>

            <div className="graph-detail-body">
              {selectedItem.type === "node" ? (
                <>
                  <div className="graph-detail-row">
                    <span className="graph-detail-label">Name</span>
                    <span className="graph-detail-value">{selectedItem.data?.name || "Unnamed"}</span>
                  </div>
                  <div className="graph-detail-row">
                    <span className="graph-detail-label">UUID</span>
                    <span className="graph-detail-value mono">
                      {selectedItem.data?.uuid || "-"}
                    </span>
                  </div>
                  <div className="graph-detail-row">
                    <span className="graph-detail-label">Created</span>
                    <span className="graph-detail-value">
                      {formatDateTime(selectedItem.data?.created_at)}
                    </span>
                  </div>
                  <div className="graph-detail-columns">
                    <div className="graph-detail-column">
                      <span className="graph-detail-column-label">Total Edges</span>
                      <span className="graph-detail-column-value">
                        {nodeEdgeStatsByNode.get(String(selectedItem.data?.uuid ?? ""))?.total ?? 0}
                      </span>
                    </div>
                    <div className="graph-detail-column">
                      <span className="graph-detail-column-label">Incoming</span>
                      <span className="graph-detail-column-value">
                        {nodeEdgeStatsByNode.get(String(selectedItem.data?.uuid ?? ""))?.incoming ?? 0}
                      </span>
                    </div>
                    <div className="graph-detail-column">
                      <span className="graph-detail-column-label">Outgoing</span>
                      <span className="graph-detail-column-value">
                        {nodeEdgeStatsByNode.get(String(selectedItem.data?.uuid ?? ""))?.outgoing ?? 0}
                      </span>
                    </div>
                  </div>

                  {selectedItem.data?.summary ? (
                    <div className="graph-detail-section">
                      <div className="graph-detail-section-title">Summary</div>
                      <div className="graph-detail-summary">{selectedItem.data.summary}</div>
                    </div>
                  ) : null}

                  {selectedItem.data?.labels?.length ? (
                    <div className="graph-detail-section">
                      <div className="graph-detail-section-title">Labels</div>
                      <div className="graph-detail-tag-list">
                        {selectedItem.data.labels.map((label) => (
                          <span className="graph-detail-tag" key={label}>
                            {label}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {selectedItem.data?.attributes &&
                  Object.keys(selectedItem.data.attributes).length > 0 ? (
                    <div className="graph-detail-section">
                      <div className="graph-detail-section-title">Properties</div>
                      <div className="graph-detail-property-list">
                        {Object.entries(selectedItem.data.attributes).map(([key, value]) => (
                          <div className="graph-detail-property" key={key}>
                            <span className="graph-detail-property-key">{key}</span>
                            <span className="graph-detail-property-value">
                              {formatFieldValue(value)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </>
              ) : selectedItem.data?.isSelfLoopGroup ? (
                <>
                  <div className="graph-detail-row">
                    <span className="graph-detail-label">Node</span>
                    <span className="graph-detail-value">
                      {selectedItem.data?.source_name || "Unknown"}
                    </span>
                  </div>
                  <div className="graph-detail-row">
                    <span className="graph-detail-label">Self Relations</span>
                    <span className="graph-detail-value">
                      {selectedItem.data?.selfLoopCount || 0}
                    </span>
                  </div>
                  <div className="graph-detail-section">
                    <div className="graph-detail-section-title">Details</div>
                    <div className="graph-detail-property-list">
                      {(selectedItem.data?.selfLoopEdges || []).map((edge, index) => (
                        <div className="graph-detail-property" key={edge.uuid || `${index}`}>
                          <span className="graph-detail-property-key">
                            {edge.name || edge.fact_type || `Relation #${index + 1}`}
                          </span>
                          <span className="graph-detail-property-value">
                            {edge.fact || formatFieldValue(edge.uuid)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="graph-detail-row">
                    <span className="graph-detail-label">Source</span>
                    <span className="graph-detail-value">
                      {selectedItem.data?.source_name ||
                        selectedItem.data?.source_node_name ||
                        selectedItem.data?.source_node_uuid ||
                        "-"}
                    </span>
                  </div>
                  <div className="graph-detail-row">
                    <span className="graph-detail-label">Target</span>
                    <span className="graph-detail-value">
                      {selectedItem.data?.target_name ||
                        selectedItem.data?.target_node_name ||
                        selectedItem.data?.target_node_uuid ||
                        "-"}
                    </span>
                  </div>
                  <div className="graph-detail-row">
                    <span className="graph-detail-label">Relation</span>
                    <span className="graph-detail-value">
                      {selectedItem.data?.name || selectedItem.data?.fact_type || "RELATED"}
                    </span>
                  </div>
                  <div className="graph-detail-row">
                    <span className="graph-detail-label">UUID</span>
                    <span className="graph-detail-value mono">
                      {selectedItem.data?.uuid || "-"}
                    </span>
                  </div>
                  <div className="graph-detail-row">
                    <span className="graph-detail-label">Fact</span>
                    <span className="graph-detail-value">
                      {selectedItem.data?.fact || "None"}
                    </span>
                  </div>
                  <div className="graph-detail-row">
                    <span className="graph-detail-label">Created</span>
                    <span className="graph-detail-value">
                      {formatDateTime(selectedItem.data?.created_at)}
                    </span>
                  </div>
                  {selectedEdgeEpisodeIds.length ? (
                    <div className="graph-detail-section">
                      <div className="graph-detail-section-title">
                        Episodes (Total: {selectedEdgeEpisodeIds.length})
                      </div>
                      <div className="graph-detail-episode-list">
                        {selectedEdgeEpisodeIds.map((episode) => (
                          <div className="graph-detail-episode-item" key={episode}>
                            {episode}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </aside>
        )}
      </div>
    </section>
  );
}
