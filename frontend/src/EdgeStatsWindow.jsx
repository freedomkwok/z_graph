import { useMemo, useState } from "react";
import DockSideToggle from "./components/DockSideToggle";

export default function EdgeStatsWindow({
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
  onSelectEdge,
  showSelectAll = false,
  onSelectAll,
  getEdgeSelectionKey,
}) {
  const edges = Array.isArray(activeWindow?.edges) ? activeWindow.edges : [];
  const selectedEdgeKey = String(windowState?.selectedEdgeKey ?? "").trim();
  const [searchText, setSearchText] = useState("");
  const searchTerm = searchText.trim().toLowerCase();
  const filteredEdges = useMemo(() => {
    if (!searchTerm) return edges;
    return edges.filter((edge) => {
      const target = String(edge?.target_node_name ?? edge?.target_node_uuid ?? "").trim().toLowerCase();
      const fact = String(edge?.fact ?? "").trim().toLowerCase();
      return target.includes(searchTerm) || fact.includes(searchTerm);
    });
  }, [edges, searchTerm]);
  if (!windowState || !activeWindow) return null;

  return (
    <div
      ref={panelRef}
      className={`edge-stats-window ${isFocused ? "focused" : ""}`}
      onMouseDown={onFocusWindow}
      style={{
        left: `${windowState.x}px`,
        top: `${windowState.y}px`,
        width: `${Number(windowState.width) || Number(defaultWidth) || 760}px`,
      }}
    >
      <div className="edge-stats-window-titlebar" onMouseDown={onBeginDrag}>
        <div className="edge-stats-window-title-group">
          <h3>{activeWindow.title}</h3>
          <p>
            Relation: <strong>{activeWindow.relation}</strong>
          </p>
        </div>
        <div className="edge-stats-window-title-actions">
          <span className="edge-stats-window-drag-hint">Drag</span>
          {windowState.bucket === "multipleSelection" ? (
            <DockSideToggle
              className="entity-filter-btn edge-stats-window-dock-toggle"
              isRight={Boolean(isDockedRight)}
              onMouseDown={(event) => event.stopPropagation()}
              onToggle={onToggleDock}
              rightTitle="Move selected pair panel to left"
              leftTitle="Move selected pair panel to right"
            />
          ) : null}
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
      <div className={`edge-stats-window-selected-bar ${activeWindow.selectedEdge ? "active" : ""}`}>
        {activeWindow.selectedEdge ? (
          <>
            Selected edge:{" "}
            {String(
              activeWindow.selectedEdge?.source_node_name ??
                activeWindow.selectedEdge?.source_node_uuid ??
                "-",
            ).trim()}
            {" -> "}
            {String(
              activeWindow.selectedEdge?.target_node_name ??
                activeWindow.selectedEdge?.target_node_uuid ??
                "-",
            ).trim()}
          </>
        ) : (
          "Select an edge row below."
        )}
      </div>
      <div className="edge-stats-popup-summary-row">
        <div className="edge-stats-popup-summary">Matching edges: {filteredEdges.length}</div>
        {showSelectAll ? (
          <button
            className="entity-filter-btn edge-stats-popup-select-all"
            type="button"
            onMouseDown={(event) => event.stopPropagation()}
            onClick={onSelectAll}
          >
            Select All
          </button>
        ) : null}
      </div>
      <div className="edge-stats-popup-search-row">
        <input
          className="graph-inspector-search"
          type="text"
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
          placeholder="Filter by target or fact"
          onMouseDown={(event) => event.stopPropagation()}
        />
      </div>
      <div className="edge-stats-popup-list">
        {edges.length === 0 ? (
          <div className="graph-inspector-empty">No edges found in this category.</div>
        ) : filteredEdges.length === 0 ? (
          <div className="graph-inspector-empty">No edges match your target/fact filter.</div>
        ) : (
          filteredEdges.map((edge, index) => {
            const source = String(edge?.source_node_name ?? edge?.source_node_uuid ?? "").trim();
            const target = String(edge?.target_node_name ?? edge?.target_node_uuid ?? "").trim();
            const fact = String(edge?.fact ?? "").trim();
            const episodes = Array.isArray(edge?.episodes) ? edge.episodes.length : 0;
            const edgeId = String(edge?.uuid ?? "").trim();
            const selectionKey = getEdgeSelectionKey(edge);
            const isSelected = selectionKey === selectedEdgeKey;
            return (
              <button
                className={`edge-stats-popup-item ${isSelected ? "active" : ""}`}
                key={`${edgeId || "edge"}-${index}`}
                type="button"
                onClick={(event) => onSelectEdge(edge, event)}
              >
                <div className="edge-stats-popup-item-top">
                  <span className="edge-stats-popup-item-title">
                    {source || "-"} {"->"} {target || "-"}
                  </span>
                  <span className="edge-stats-popup-item-episodes">episodes: {episodes}</span>
                </div>
                {fact ? <div className="edge-stats-popup-item-fact">{fact}</div> : null}
                {edgeId ? <div className="edge-stats-popup-item-meta">uuid: {edgeId}</div> : null}
              </button>
            );
          })
        )}
      </div>
      <div className="edge-stats-window-resize-handle" onMouseDown={onBeginResize} />
    </div>
  );
}
