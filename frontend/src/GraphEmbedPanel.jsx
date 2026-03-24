import { useTaskStore } from "./taskStore";

const ZEP_EMBED_URL = import.meta.env.VITE_ZEP_EMBED_URL ?? "https://app.getzep.com";
const ZEP_GRAPH_URL_TEMPLATE = import.meta.env.VITE_ZEP_GRAPH_URL_TEMPLATE ?? "";

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

export default function GraphEmbedPanel() {
  const { state, refreshGraphFrame, setViewMode } = useTaskStore();
  const frameSrc = resolveGraphEmbedUrl(state.currentProject);
  const isGraphOnly = state.viewMode === "graph";

  return (
    <section className="left-panel">
      <div className="panel-header">
        <div className="panel-title">
          <span className="panel-icon">◆</span>
          Graph
        </div>
        <div className="graph-panel-actions">
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
            onClick={refreshGraphFrame}
            title="Refresh embedded graph"
          >
            ↻
          </button>
        </div>
      </div>
      <div className="graph-frame-wrap">
        <iframe
          key={state.iframeVersion}
          className="graph-frame"
          title="Zep Graph"
          src={frameSrc}
          referrerPolicy="no-referrer"
        />
      </div>
    </section>
  );
}
