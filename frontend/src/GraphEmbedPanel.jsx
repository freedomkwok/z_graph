import { useTaskStore } from "./taskStore";

const ZEP_EMBED_URL = import.meta.env.VITE_ZEP_EMBED_URL ?? "https://app.getzep.com";

export default function GraphEmbedPanel() {
  const { state, refreshGraphFrame } = useTaskStore();

  return (
    <section className="left-panel">
      <div className="panel-header">
        <div className="panel-title">
          <span className="panel-icon">◆</span>
          Graph Relationship Visualization
        </div>
        <button
          className="icon-btn"
          type="button"
          onClick={refreshGraphFrame}
          title="Refresh embedded graph"
        >
          ↻
        </button>
      </div>
      <div className="graph-frame-wrap">
        <iframe
          key={state.iframeVersion}
          className="graph-frame"
          title="Zep Graph"
          src={ZEP_EMBED_URL}
          referrerPolicy="no-referrer"
        />
      </div>
    </section>
  );
}
