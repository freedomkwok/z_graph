import { getPreferredPromptLabel } from "../utils";

/** Coalesce concurrent / Strict Mode double-mount list calls into one HTTP request. */
let promptLabelListInFlight = null;
/** After a fast response, React 18 Strict Mode may run the startup effect again; reuse result briefly. */
let promptLabelListLastOk = null;
const PROMPT_LABEL_LIST_DEDUP_MS = 750;

function createPromptLabelActions({ state, dispatch, addSystemLog, setFormField, withApiBase, trackedFetch }) {
  const applySyncFormLabel = (labels, syncFormLabel) => {
    if (!syncFormLabel) {
      return;
    }
    const nextPromptLabel = getPreferredPromptLabel(labels, state.form.promptLabel);
    setFormField("promptLabel", nextPromptLabel);
  };

  const fetchPromptLabels = async ({ syncFormLabel = true, skipDedup = false } = {}) => {
    if (skipDedup) {
      promptLabelListLastOk = null;
    }

    const now = Date.now();
    if (
      !skipDedup &&
      Array.isArray(promptLabelListLastOk?.labels) &&
      now - (promptLabelListLastOk?.completedAt ?? 0) < PROMPT_LABEL_LIST_DEDUP_MS
    ) {
      const labels = promptLabelListLastOk.labels;
      applySyncFormLabel(labels, syncFormLabel);
      return labels;
    }

    if (!skipDedup && promptLabelListInFlight) {
      const labels = await promptLabelListInFlight;
      applySyncFormLabel(labels, syncFormLabel);
      return labels;
    }

    if (skipDedup && promptLabelListInFlight) {
      await promptLabelListInFlight;
    }

    const run = (async () => {
      dispatch({
        type: "PATCH_PROMPT_LABEL_CATALOG",
        payload: { loading: true, error: "" },
      });
      try {
        const response = await trackedFetch(withApiBase("/api/prompt-label/list"), undefined, {
          source: "api",
        });
        const payload = await response.json();
        if (!response.ok || !payload?.success) {
          throw new Error(payload?.error ?? "Failed to list category labels");
        }

        const labels = Array.isArray(payload?.data) ? payload.data : [];
        const parsedTotalLabels = Number(payload?.total_labels);
        const totalLabels = Number.isFinite(parsedTotalLabels) ? parsedTotalLabels : labels.length;
        dispatch({
          type: "SET_PROMPT_LABEL_CATALOG",
          payload: { loading: false, error: "", items: labels, totalLabels },
        });

        promptLabelListLastOk = { labels, completedAt: Date.now() };
        return labels;
      } catch (error) {
        dispatch({
          type: "PATCH_PROMPT_LABEL_CATALOG",
          payload: {
            loading: false,
            error: String(error),
            totalLabels: state.promptLabelCatalog.totalLabels,
          },
        });
        addSystemLog(`Exception in listPromptLabels: ${String(error)}`);
        return [];
      }
    })();

    promptLabelListInFlight = run;

    try {
      const labels = await run;
      applySyncFormLabel(labels, syncFormLabel);
      return labels;
    } finally {
      promptLabelListInFlight = null;
    }
  };

  const createPromptLabel = async (name) => {
    const normalizedName = String(name ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }

    const response = await trackedFetch(
      withApiBase("/api/prompt-label"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: normalizedName }),
      },
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to create category label");
    }

    await fetchPromptLabels({ syncFormLabel: false, skipDedup: true });
    addSystemLog(`Category label saved: ${payload?.data?.name ?? normalizedName}`);
    return payload?.data;
  };

  const deletePromptLabel = async (name) => {
    const normalizedName = String(name ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }

    const response = await trackedFetch(
      withApiBase(`/api/prompt-label/${encodeURIComponent(normalizedName)}`),
      {
        method: "DELETE",
      },
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to delete category label");
    }

    const labels = await fetchPromptLabels({ syncFormLabel: false, skipDedup: true });
    const nextPromptLabel = getPreferredPromptLabel(labels, state.form.promptLabel);
    if (nextPromptLabel !== state.form.promptLabel) {
      setFormField("promptLabel", nextPromptLabel);
    }
    addSystemLog(`Category label deleted: ${normalizedName}`);
    return true;
  };

  const syncPromptLabelFromLangfuse = async (name) => {
    const normalizedName = String(name ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }

    const response = await trackedFetch(
      withApiBase(`/api/prompt-label/${encodeURIComponent(normalizedName)}/sync-from-langfuse`),
      { method: "POST" },
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to sync category label defaults");
    }

    await fetchPromptLabels({ syncFormLabel: false, skipDedup: true });
    const downloadedFiles = Number(payload?.data?.downloaded_files ?? 0);
    addSystemLog(
      `Category label synced from default: ${normalizedName} (${downloadedFiles} file${downloadedFiles === 1 ? "" : "s"})`,
    );
    return payload?.data;
  };

  const generatePromptLabelTypeListsFromLlm = async (
    name,
    {
      projectId,
      entityEdgeGeneratorPromptContent,
      usePdfPageRange = false,
      pdfPageFrom = 1,
      pdfPageTo = 100,
    } = {},
  ) => {
    const normalizedName = String(name ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }
    const normalizedProjectId = String(projectId ?? "").trim();
    if (!normalizedProjectId) {
      throw new Error("project_id is required");
    }
    const normalizedPdfPageFrom = Math.max(1, Number.parseInt(String(pdfPageFrom ?? ""), 10) || 1);
    const normalizedPdfPageTo = Math.max(1, Number.parseInt(String(pdfPageTo ?? ""), 10) || 100);
    const resolvedPdfPageFrom = Math.min(normalizedPdfPageFrom, normalizedPdfPageTo);
    const resolvedPdfPageTo = Math.max(normalizedPdfPageFrom, normalizedPdfPageTo);

    const response = await trackedFetch(
      withApiBase(`/api/prompt-label/${encodeURIComponent(normalizedName)}/generate-from-llm`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: normalizedProjectId,
          pdf_page_from: Boolean(usePdfPageRange) ? resolvedPdfPageFrom : undefined,
          pdf_page_to: Boolean(usePdfPageRange) ? resolvedPdfPageTo : undefined,
          entity_edge_generator_prompt_content:
            typeof entityEdgeGeneratorPromptContent === "string"
              ? entityEdgeGeneratorPromptContent
              : undefined,
        }),
      },
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to generate category label type lists from LLM");
    }

    const processedDocuments = Number(payload?.data?.processed_documents ?? 0);
    addSystemLog(
      `Category label generated by LLM: ${normalizedName} (${processedDocuments} document${processedDocuments === 1 ? "" : "s"})`,
    );
    return payload?.data;
  };

  const createDraftProject = async ({
    projectName = "",
    promptLabel = "",
    graphBackend = "",
    projectId = "",
    usePdfPageRange = false,
    pdfPageFrom = 1,
    pdfPageTo = 100,
    files = [],
  } = {}) => {
    const formData = new FormData();
    const normalizedProjectName = String(projectName ?? "").trim();
    const normalizedPromptLabel = String(promptLabel ?? "").trim();
    const normalizedGraphBackend = String(graphBackend ?? "").trim();
    const normalizedProjectId = String(projectId ?? "").trim();
    const normalizedPdfPageFrom = Math.max(1, Number.parseInt(String(pdfPageFrom ?? ""), 10) || 1);
    const normalizedPdfPageTo = Math.max(1, Number.parseInt(String(pdfPageTo ?? ""), 10) || 100);
    const resolvedPdfPageFrom = Math.min(normalizedPdfPageFrom, normalizedPdfPageTo);
    const resolvedPdfPageTo = Math.max(normalizedPdfPageFrom, normalizedPdfPageTo);

    if (normalizedProjectName) formData.append("project_name", normalizedProjectName);
    if (normalizedPromptLabel) formData.append("prompt_label", normalizedPromptLabel);
    if (normalizedGraphBackend) formData.append("graph_backend", normalizedGraphBackend);
    if (normalizedProjectId) formData.append("project_id", normalizedProjectId);
    if (Boolean(usePdfPageRange)) {
      formData.append("pdf_page_from", String(resolvedPdfPageFrom));
      formData.append("pdf_page_to", String(resolvedPdfPageTo));
    }
    for (const file of Array.isArray(files) ? files : []) {
      if (file) {
        formData.append("files", file);
      }
    }

    const response = await trackedFetch(
      withApiBase("/api/project/draft"),
      {
        method: "POST",
        body: formData,
      },
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to prepare draft project");
    }

    const resolvedProjectId = String(payload?.data?.project_id ?? "").trim();
    addSystemLog(
      resolvedProjectId
        ? `Draft project prepared: ${resolvedProjectId}`
        : "Draft project prepared",
    );
    return payload?.data;
  };

  const getPromptLabelTypeLists = async (name, { projectId } = {}) => {
    const normalizedName = String(name ?? "").trim();
    const normalizedProjectId = String(projectId ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }

    const params = new URLSearchParams();
    if (normalizedProjectId) {
      params.set("project_id", normalizedProjectId);
    }
    const query = params.toString();
    const response = await trackedFetch(
      withApiBase(
        `/api/prompt-label/${encodeURIComponent(normalizedName)}/types${query ? `?${query}` : ""}`,
      ),
      undefined,
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to load category label type lists");
    }
    return payload?.data;
  };

  const getPromptLabelPromptTemplate = async (name, promptKey, { projectId } = {}) => {
    const normalizedName = String(name ?? "").trim();
    const normalizedPromptKey = String(promptKey ?? "").trim();
    const normalizedProjectId = String(projectId ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }
    if (!normalizedPromptKey) {
      throw new Error("prompt_key is required");
    }

    const params = new URLSearchParams();
    if (normalizedProjectId) {
      params.set("project_id", normalizedProjectId);
    }
    const query = params.toString();
    const response = await trackedFetch(
      withApiBase(
        `/api/prompt-label/${encodeURIComponent(normalizedName)}/prompt-template/${encodeURIComponent(normalizedPromptKey)}${query ? `?${query}` : ""}`,
      ),
      undefined,
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to load prompt template");
    }
    return payload?.data;
  };

  const updatePromptLabelPromptTemplate = async (name, promptKey, content, { projectId } = {}) => {
    const normalizedName = String(name ?? "").trim();
    const normalizedPromptKey = String(promptKey ?? "").trim();
    const normalizedProjectId = String(projectId ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }
    if (!normalizedPromptKey) {
      throw new Error("prompt_key is required");
    }

    const response = await trackedFetch(
      withApiBase(
        `/api/prompt-label/${encodeURIComponent(normalizedName)}/prompt-template/${encodeURIComponent(normalizedPromptKey)}`,
      ),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: String(content ?? ""),
          project_id: normalizedProjectId || undefined,
        }),
      },
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to update prompt template");
    }
    addSystemLog(`Prompt template updated: ${normalizedName} (${normalizedPromptKey})`);
    return payload?.data;
  };

  const syncPromptLabelPromptTemplateFromDefault = async (name, promptKey, { projectId } = {}) => {
    const normalizedName = String(name ?? "").trim();
    const normalizedPromptKey = String(promptKey ?? "").trim();
    const normalizedProjectId = String(projectId ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }
    if (!normalizedPromptKey) {
      throw new Error("prompt_key is required");
    }

    const params = new URLSearchParams();
    if (normalizedProjectId) {
      params.set("project_id", normalizedProjectId);
    }
    const query = params.toString();
    const response = await trackedFetch(
      withApiBase(
        `/api/prompt-label/${encodeURIComponent(normalizedName)}/prompt-template/${encodeURIComponent(normalizedPromptKey)}/sync-from-default${query ? `?${query}` : ""}`,
      ),
      undefined,
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to sync prompt template from default");
    }
    addSystemLog(`Prompt template synced from default: ${normalizedName} (${normalizedPromptKey})`);
    return payload?.data;
  };

  const updatePromptLabelTypeLists = async (name, typeLists, { projectId } = {}) => {
    const normalizedName = String(name ?? "").trim();
    const normalizedProjectId = String(projectId ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }

    const response = await trackedFetch(
      withApiBase(`/api/prompt-label/${encodeURIComponent(normalizedName)}/types`),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          individual: Array.isArray(typeLists?.individual) ? typeLists.individual : [],
          individual_exception: Array.isArray(typeLists?.individual_exception)
            ? typeLists.individual_exception
            : [],
          organization: Array.isArray(typeLists?.organization) ? typeLists.organization : [],
          organization_exception: Array.isArray(typeLists?.organization_exception)
            ? typeLists.organization_exception
            : [],
          relationship: Array.isArray(typeLists?.relationship) ? typeLists.relationship : [],
          relationship_exception: Array.isArray(typeLists?.relationship_exception)
            ? typeLists.relationship_exception
            : [],
          project_id: normalizedProjectId || undefined,
        }),
      },
      { source: "api" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to update category label type lists");
    }
    addSystemLog(`Category label type lists updated: ${normalizedName}`);
    return payload?.data;
  };

  return {
    fetchPromptLabels,
    createPromptLabel,
    deletePromptLabel,
    syncPromptLabelFromLangfuse,
    generatePromptLabelTypeListsFromLlm,
    createDraftProject,
    getPromptLabelTypeLists,
    getPromptLabelPromptTemplate,
    updatePromptLabelPromptTemplate,
    syncPromptLabelPromptTemplateFromDefault,
    updatePromptLabelTypeLists,
  };
}

export { createPromptLabelActions };
