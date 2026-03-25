export default function GraphInspectorPanel({
  inspectorTab,
  setInspectorTab,
  handleSelectAllEntityTypes,
  allTypesSelected,
  handleClearEntityTypes,
  selectedTypeCount,
  entityTypeSearchText,
  setEntityTypeSearchText,
  visibleEntityTypeOptions,
  activeEntityTypeSet,
  toggleEntityType,
  handleSelectAllEdgeTypes,
  allEdgeTypesSelected,
  handleClearEdgeTypes,
  selectedEdgeTypeCount,
  edgeTypeSearchText,
  setEdgeTypeSearchText,
  visibleEdgeTypeOptions,
  activeEdgeTypeSet,
  toggleEdgeType,
  selectedEdgeStats,
  selectedEdgeEpisodeIds,
}) {
  return (
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
              <div className="graph-inspector-empty">No entity types match the filter text.</div>
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
              <div className="edge-stats-relation-name">Relation: {selectedEdgeStats.relation}</div>
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
  );
}
