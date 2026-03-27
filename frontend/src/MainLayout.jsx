import { useEffect, useRef, useState } from "react";

import GraphEmbedPanel from "./GraphEmbedPanel";
import TaskPanel from "./TaskPanel";
import TopBar from "./TopBar";
import { useTaskStore } from "./TaskStore/index";

const DEFAULT_RIGHT_PANEL_WIDTH = 440;
const MIN_RIGHT_PANEL_WIDTH = 320;
const MIN_LEFT_PANEL_WIDTH = 360;

function clampRightPanelWidth(desiredWidth, totalWidth) {
  const min = MIN_RIGHT_PANEL_WIDTH;
  const max = Math.max(min, totalWidth - MIN_LEFT_PANEL_WIDTH);
  return Math.min(Math.max(desiredWidth, min), max);
}

export default function MainLayout({ currentPage = "workspace", onNavigate }) {
  const { state } = useTaskStore();
  const workspaceRef = useRef(null);
  const isResizingRef = useRef(false);
  const [isResizing, setIsResizing] = useState(false);
  const [rightPanelWidth, setRightPanelWidth] = useState(() => {
    const saved = Number(window.localStorage.getItem("z_graph.right_panel_width"));
    if (Number.isFinite(saved) && saved > 0) {
      return saved;
    }
    return DEFAULT_RIGHT_PANEL_WIDTH;
  });

  const startResize = (event) => {
    if (state.viewMode !== "both") return;
    if (event.currentTarget?.setPointerCapture) {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    isResizingRef.current = true;
    setIsResizing(true);
    document.body.classList.add("panel-resizing");
    event.preventDefault();
  };

  useEffect(() => {
    const stopResize = () => {
      if (!isResizingRef.current) return;
      isResizingRef.current = false;
      setIsResizing(false);
      document.body.classList.remove("panel-resizing");
    };

    const onPointerMove = (event) => {
      if (!isResizingRef.current || !workspaceRef.current) return;
      if ((event.buttons & 1) !== 1) {
        stopResize();
        return;
      }
      const rect = workspaceRef.current.getBoundingClientRect();
      const nextWidth = rect.right - event.clientX;
      setRightPanelWidth(clampRightPanelWidth(nextWidth, rect.width));
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
    window.addEventListener("mouseup", stopResize);
    window.addEventListener("blur", stopResize);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
      window.removeEventListener("mouseup", stopResize);
      window.removeEventListener("blur", stopResize);
      document.body.classList.remove("panel-resizing");
    };
  }, []);

  useEffect(() => {
    window.localStorage.setItem("z_graph.right_panel_width", String(rightPanelWidth));
  }, [rightPanelWidth]);

  const isBothMode = state.viewMode === "both";
  const isBackendOnly = state.viewMode === "backend";
  const isGraphOnly = state.viewMode === "graph";
  const workspaceClass = `workspace ${isBackendOnly ? "backend-only" : ""} ${isGraphOnly ? "graph-only" : ""} ${isBothMode ? "with-splitter" : ""
    } ${isResizing ? "is-resizing" : ""}`;
  const workspaceStyle = isBothMode
    ? { gridTemplateColumns: `minmax(0, 1fr) 10px ${rightPanelWidth}px` }
    : undefined;

  return (
    <div className="app-shell">
      <TopBar currentPage={currentPage} onNavigate={onNavigate} />
      <main className={workspaceClass} ref={workspaceRef} style={workspaceStyle}>
        {!isGraphOnly && <TaskPanel />}
        {isBothMode && (
          <div
            className="panel-splitter"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize panels"
            onPointerDown={startResize}
          />
        )}
        {!isBackendOnly && <GraphEmbedPanel />}
      </main>
    </div>
  );
}
