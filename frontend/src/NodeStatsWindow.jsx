import DockSideToggle from "./components/DockSideToggle";

export default function NodeStatsWindow({
  panelRef,
  windowState,
  activeWindow,
  isFocused = false,
  onFocusWindow,
  defaultWidth,
  onBeginDrag,
  onBeginResize,
  onToggleDock,
  isDockedRight,
  onClose,
  onSelectNode,
  onSelectEdge,
  getNodeSelectionKey,
}) {
  if (!windowState || !activeWindow) return null;

  const selectedNodeKey = String(windowState.selectedNodeKey ?? "").trim();
  const groupedEdges = activeWindow.groupedEdges ?? null;
  const nodeOne = groupedEdges?.nodeOne ?? null;
  const nodeTwo = groupedEdges?.nodeTwo ?? null;
  const nodeOneOnlyEdges = Array.isArray(groupedEdges?.nodeOneOnlyEdges)
    ? groupedEdges.nodeOneOnlyEdges
    : [];
  const sharedEdges = Array.isArray(groupedEdges?.sharedEdges) ? groupedEdges.sharedEdges : [];
  const nodeTwoOnlyEdges = Array.isArray(groupedEdges?.nodeTwoOnlyEdges)
    ? groupedEdges.nodeTwoOnlyEdges
    : [];
  const nodeOneLabel = String(groupedEdges?.nodeOneLabel ?? "Node1");
  const nodeTwoLabel = String(groupedEdges?.nodeTwoLabel ?? "Node2");
  const hasTwoNodes = Boolean(groupedEdges?.hasTwoNodes && nodeOne && nodeTwo);
  const hasNodeOneOnlyEdges = nodeOneOnlyEdges.length > 0;
  const hasSharedEdges = sharedEdges.length > 0;
  const hasNodeTwoOnlyEdges = nodeTwoOnlyEdges.length > 0;
  const selectedEdgeKey = String(activeWindow.selectedEdgeKey ?? "").trim();

  const getEdgeDisplayLine = (edge) => {
    const source = String(edge?.source_node_name ?? edge?.source_node_uuid ?? "-").trim() || "-";
    const target = String(edge?.target_node_name ?? edge?.target_node_uuid ?? "-").trim() || "-";
    return `${source} -> ${target}`;
  };

  const getEdgeMetaLine = (edge) => {
    const relation = String(edge?.name ?? edge?.fact_type ?? "RELATED").trim() || "RELATED";
    const fact = String(edge?.fact ?? "").trim();
    return fact ? `${relation} · ${fact}` : relation;
  };
  const getEdgeSelectionKey = (edge) => {
    const edgeUuid = String(edge?.uuid ?? "").trim();
    if (edgeUuid) return `uuid:${edgeUuid}`;
    const source = String(edge?.source_node_uuid ?? edge?.source_uuid ?? "").trim();
    const target = String(edge?.target_node_uuid ?? edge?.target_uuid ?? "").trim();
    const relation = String(edge?.name ?? edge?.fact_type ?? "RELATED").trim() || "RELATED";
    const fact = String(edge?.fact ?? "").trim();
    return `${source}->${target}|${relation}|${fact}`;
  };

  const renderEdgeItems = (edges, keyPrefix) => {
    return edges.map((edge, index) => {
      const edgeSelectionKey = getEdgeSelectionKey(edge);
      const edgeKey = `${keyPrefix}-${edgeSelectionKey || index}`;
      const isSelectedEdge = edgeSelectionKey === selectedEdgeKey;
      return (
        <button
          className={`node-stats-edge-item ${isSelectedEdge ? "active" : ""}`}
          key={edgeKey}
          type="button"
          onClick={() => onSelectEdge(edge)}
        >
          <div className="node-stats-edge-line">{getEdgeDisplayLine(edge)}</div>
          <div className="node-stats-edge-meta">{getEdgeMetaLine(edge)}</div>
        </button>
      );
    });
  };

  return (
    <div
      ref={panelRef}
      className={`edge-stats-window node-stats-window ${isFocused ? "focused" : ""}`}
      onMouseDown={onFocusWindow}
      style={{
        left: `${windowState.x}px`,
        top: `${windowState.y}px`,
        width: `${Number(windowState.width) || Number(defaultWidth) || 460}px`,
      }}
    >
      <div className="edge-stats-window-titlebar node-stats-window-titlebar" onMouseDown={onBeginDrag}>
        <div className="edge-stats-window-title-group">
          <h3>{activeWindow.title}</h3>
          <p>{activeWindow.relation}</p>
        </div>
        <div className="edge-stats-window-title-actions">
          <span className="edge-stats-window-drag-hint">Drag</span>
          <DockSideToggle
            className="entity-filter-btn edge-stats-window-dock-toggle"
            isRight={Boolean(isDockedRight)}
            onMouseDown={(event) => event.stopPropagation()}
            onToggle={onToggleDock}
            rightTitle="Move selected nodes panel to left"
            leftTitle="Move selected nodes panel to right"
          />
          <button
            className="entity-filter-btn edge-stats-popup-close"
            type="button"
            onMouseDown={(event) => event.stopPropagation()}
            onClick={onClose}
          >
            Close
          </button>
        </div>
      </div>
      <div className={`edge-stats-window-selected-bar ${activeWindow.selectedNode ? "active" : ""}`}>
        {activeWindow.selectedNode ? (
          <>
            Focused node:{" "}
            <strong>{String(activeWindow.selectedNode?.name ?? "Unnamed").trim() || "Unnamed"}</strong>
            {" · "}
            <span>{activeWindow.selectedEntityType || "Entity"}</span>
          </>
        ) : (
          "Select a node row below."
        )}
      </div>
      <div className="edge-stats-popup-summary-row node-stats-popup-summary-row">
        <div className="edge-stats-popup-summary">
          Selected nodes: {activeWindow.nodes.length}
          {hasTwoNodes ? ` · Shared pair: ${nodeOneLabel} <-> ${nodeTwoLabel}` : ""}
        </div>
      </div>
      <div className="edge-stats-popup-list node-stats-popup-list">
        {activeWindow.nodes.length === 0 ? (
          <div className="graph-inspector-empty">No selected nodes.</div>
        ) : (
          <>
            <div className="node-stats-selected-node-list">
              {activeWindow.nodes.map((node, index) => {
                const nodeName = String(node?.name ?? "").trim() || "Unnamed";
                const nodeType = String(
                  node?.labels?.find((label) => label !== "Entity" && label !== "Node") ?? "Entity",
                );
                const nodeUuid = String(node?.uuid ?? "").trim();
                const selectionKey = getNodeSelectionKey(node);
                const isSelected = selectionKey === selectedNodeKey;
                return (
                  <button
                    className={`edge-stats-popup-item node-stats-popup-item ${isSelected ? "active" : ""}`}
                    key={`${selectionKey || "node"}-${index}`}
                    type="button"
                    onClick={() => onSelectNode(node)}
                  >
                    <div className="edge-stats-popup-item-top">
                      <span className="edge-stats-popup-item-title">{nodeName}</span>
                      <span className="node-stats-popup-item-type">{nodeType}</span>
                    </div>
                    {nodeUuid ? <div className="edge-stats-popup-item-meta">uuid: {nodeUuid}</div> : null}
                  </button>
                );
              })}
            </div>

            {hasNodeOneOnlyEdges || hasSharedEdges || hasNodeTwoOnlyEdges ? (
              <div className="node-stats-edge-groups-wrapper">
                {hasNodeOneOnlyEdges ? (
                  <section className="node-stats-edge-group-block node-stats-edge-group-node-one">
                    <div className="node-stats-edge-group-label">{nodeOneLabel} Edges</div>
                    <div className="node-stats-edge-group-list">
                      {renderEdgeItems(nodeOneOnlyEdges, "node-one")}
                    </div>
                  </section>
                ) : null}
                {hasSharedEdges ? (
                  <section className="node-stats-edge-group-block node-stats-edge-group-shared">
                    <div className="node-stats-edge-group-label">Shared Edges</div>
                    <div className="node-stats-edge-group-list">
                      {renderEdgeItems(sharedEdges, "shared")}
                    </div>
                  </section>
                ) : null}
                {hasNodeTwoOnlyEdges ? (
                  <section className="node-stats-edge-group-block node-stats-edge-group-node-two">
                    <div className="node-stats-edge-group-label">{nodeTwoLabel} Edges</div>
                    <div className="node-stats-edge-group-list">
                      {renderEdgeItems(nodeTwoOnlyEdges, "node-two")}
                    </div>
                  </section>
                ) : null}
              </div>
            ) : null}
          </>
        )}
      </div>
      <div className="edge-stats-window-resize-handle" onMouseDown={onBeginResize} />
    </div>
  );
}
