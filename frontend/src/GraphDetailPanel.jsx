import DockSideToggle from "./components/DockSideToggle";

export default function GraphDetailPanel({
  selectedItem,
  closeDetail,
  detailPanelSide = "right",
  toggleDetailPanelSide,
  panelRef,
  panelStyle,
  onBeginDrag,
  isCustomPosition = false,
  formatDateTime,
  formatFieldValue,
  nodeEdgeStatsByNode,
  selectedEdgeEpisodeIds,
}) {
  if (!selectedItem) return null;

  return (
    <aside
      className={`graph-detail-panel ${
        isCustomPosition
          ? "graph-detail-panel-custom"
          : detailPanelSide === "left"
            ? "graph-detail-panel-left"
            : "graph-detail-panel-right"
      }`}
      ref={panelRef}
      style={panelStyle}
    >
      <div className="graph-detail-head" onMouseDown={onBeginDrag}>
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
        <div className="graph-detail-head-actions">
          <DockSideToggle
            className="graph-detail-dock-toggle"
            isRight={detailPanelSide === "right"}
            onToggle={toggleDetailPanelSide}
            rightTitle="Move detail panel to left"
            leftTitle="Move detail panel to right"
          />
          <button className="graph-detail-close" type="button" onClick={closeDetail}>
            ×
          </button>
        </div>
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
              <span className="graph-detail-value mono">{selectedItem.data?.uuid || "-"}</span>
            </div>
            <div className="graph-detail-row">
              <span className="graph-detail-label">Created</span>
              <span className="graph-detail-value">{formatDateTime(selectedItem.data?.created_at)}</span>
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

            {selectedItem.data?.attributes && Object.keys(selectedItem.data.attributes).length > 0 ? (
              <div className="graph-detail-section">
                <div className="graph-detail-section-title">Properties</div>
                <div className="graph-detail-property-list">
                  {Object.entries(selectedItem.data.attributes).map(([key, value]) => (
                    <div className="graph-detail-property" key={key}>
                      <span className="graph-detail-property-key">{key}</span>
                      <span className="graph-detail-property-value">{formatFieldValue(value)}</span>
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
              <span className="graph-detail-value">{selectedItem.data?.source_name || "Unknown"}</span>
            </div>
            <div className="graph-detail-row">
              <span className="graph-detail-label">Self Relations</span>
              <span className="graph-detail-value">{selectedItem.data?.selfLoopCount || 0}</span>
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
              <span className="graph-detail-value mono">{selectedItem.data?.uuid || "-"}</span>
            </div>
            <div className="graph-detail-row">
              <span className="graph-detail-label">Fact</span>
              <span className="graph-detail-value">{selectedItem.data?.fact || "None"}</span>
            </div>
            <div className="graph-detail-row">
              <span className="graph-detail-label">Created</span>
              <span className="graph-detail-value">{formatDateTime(selectedItem.data?.created_at)}</span>
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
  );
}
