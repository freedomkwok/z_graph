import { getPreferredPromptLabel } from "../utils";

function createPromptLabelActions({ state, dispatch, addSystemLog, setFormField, withApiBase }) {
  const fetchPromptLabels = async ({ syncFormLabel = true } = {}) => {
    dispatch({
      type: "PATCH_PROMPT_LABEL_CATALOG",
      payload: { loading: true, error: "" },
    });
    try {
      const response = await fetch(withApiBase("/api/prompt-label/list"));
      const payload = await response.json();
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error ?? "Failed to list prompt labels");
      }

      const labels = Array.isArray(payload?.data) ? payload.data : [];
      const parsedTotalLabels = Number(payload?.total_labels);
      const totalLabels = Number.isFinite(parsedTotalLabels) ? parsedTotalLabels : labels.length;
      dispatch({
        type: "SET_PROMPT_LABEL_CATALOG",
        payload: { loading: false, error: "", items: labels, totalLabels },
      });

      if (syncFormLabel) {
        const nextPromptLabel = getPreferredPromptLabel(labels, state.form.promptLabel);
        setFormField("promptLabel", nextPromptLabel);
      }
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
  };

  const createPromptLabel = async (name) => {
    const normalizedName = String(name ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }

    const response = await fetch(withApiBase("/api/prompt-label"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: normalizedName }),
    });
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to create prompt label");
    }

    await fetchPromptLabels({ syncFormLabel: false });
    addSystemLog(`Prompt label saved: ${payload?.data?.name ?? normalizedName}`);
    return payload?.data;
  };

  const deletePromptLabel = async (name) => {
    const normalizedName = String(name ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }

    const response = await fetch(withApiBase(`/api/prompt-label/${encodeURIComponent(normalizedName)}`), {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to delete prompt label");
    }

    const labels = await fetchPromptLabels({ syncFormLabel: false });
    const nextPromptLabel = getPreferredPromptLabel(labels, state.form.promptLabel);
    if (nextPromptLabel !== state.form.promptLabel) {
      setFormField("promptLabel", nextPromptLabel);
    }
    addSystemLog(`Prompt label deleted: ${normalizedName}`);
    return true;
  };

  const syncPromptLabelFromLangfuse = async (name) => {
    const normalizedName = String(name ?? "").trim();
    if (!normalizedName) {
      throw new Error("Label name is required");
    }

    const response = await fetch(
      withApiBase(`/api/prompt-label/${encodeURIComponent(normalizedName)}/sync-from-langfuse`),
      { method: "POST" },
    );
    const payload = await response.json();
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error ?? "Failed to sync prompts from Langfuse");
    }

    await fetchPromptLabels({ syncFormLabel: false });
    const downloadedFiles = Number(payload?.data?.downloaded_files ?? 0);
    addSystemLog(
      `Prompt label synced from Langfuse: ${normalizedName} (${downloadedFiles} file${downloadedFiles === 1 ? "" : "s"})`,
    );
    return payload?.data;
  };

  return {
    fetchPromptLabels,
    createPromptLabel,
    deletePromptLabel,
    syncPromptLabelFromLangfuse,
  };
}

export { createPromptLabelActions };
