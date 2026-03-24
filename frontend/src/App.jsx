import { useEffect, useState } from "react";

import MainLayout from "./MainLayout";
import PromptLabelManagementPage from "./PromptLabelManagementPage";
import ProjectManagementPage from "./ProjectManagementPage";
import { TaskStoreProvider } from "./taskStore";

function getPageFromPath(pathname) {
  const normalized = String(pathname ?? "/").toLowerCase();
  if (normalized.startsWith("/settings/prompt-labels")) {
    return "prompt-labels";
  }
  if (normalized.startsWith("/projects")) {
    return "projects";
  }
  return "workspace";
}

function App() {
  const [currentPage, setCurrentPage] = useState(() => getPageFromPath(window.location.pathname));

  useEffect(() => {
    const onPopState = () => {
      setCurrentPage(getPageFromPath(window.location.pathname));
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = (nextPath) => {
    const normalized = String(nextPath ?? "/").toLowerCase();
    let target = "/";
    if (normalized.startsWith("/projects")) {
      target = "/projects";
    } else if (normalized.startsWith("/settings/prompt-labels")) {
      target = "/settings/prompt-labels";
    }
    if (window.location.pathname !== target) {
      window.history.pushState({}, "", target);
    }
    setCurrentPage(getPageFromPath(target));
  };

  return (
    <TaskStoreProvider>
      {currentPage === "projects" ? (
        <ProjectManagementPage onNavigate={navigate} />
      ) : currentPage === "prompt-labels" ? (
        <PromptLabelManagementPage onNavigate={navigate} />
      ) : (
        <MainLayout currentPage={currentPage} onNavigate={navigate} />
      )}
    </TaskStoreProvider>
  );
}

export default App;
