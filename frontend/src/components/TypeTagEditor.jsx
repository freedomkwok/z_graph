import { useEffect, useRef, useState } from "react";

import TagChip from "./TagChip";

const normalizeTag = (value) =>
  String(value ?? "")
    .trim()
    .replace(/\s+/g, " ");

export default function TypeTagEditor({
  title,
  tags,
  onChange,
  onOpenProperties,
  placeholder,
  autoFocus = false,
  highlighted = false,
  removeMode = false,
  onToggleRemoveMode,
  selectedIndexes = [],
  onToggleSelect,
  onMergeSelected,
  changedTagNames = [],
  readOnly = false,
}) {
  const [inputValue, setInputValue] = useState("");
  const [searchValue, setSearchValue] = useState("");
  const addInputRef = useRef(null);

  useEffect(() => {
    if (!autoFocus) return;
    addInputRef.current?.focus();
  }, [autoFocus]);

  const hasDuplicate = (nextValue) =>
    tags.some((tag) => normalizeTag(tag).toLowerCase() === normalizeTag(nextValue).toLowerCase());

  const appendTag = () => {
    if (readOnly) return;
    const normalized = normalizeTag(inputValue);
    if (!normalized || hasDuplicate(normalized)) {
      setInputValue("");
      return;
    }
    onChange([...tags, normalized]);
    setInputValue("");
  };

  const removeTagAt = (targetIndex) => {
    if (readOnly) return;
    onChange(tags.filter((_, index) => index !== targetIndex));
  };

  const showRemoveControls = Boolean(removeMode) && typeof onToggleRemoveMode === "function";
  const selectedSet = new Set(Array.isArray(selectedIndexes) ? selectedIndexes : []);
  const normalizedSearch = String(searchValue ?? "").trim().toLowerCase();
  const visibleTags = tags
    .map((tag, index) => ({ tag, index }))
    .filter(({ tag }) => {
      if (!normalizedSearch) return true;
      return normalizeTag(tag).toLowerCase().includes(normalizedSearch);
    });
  const changedSet = new Set(
    (Array.isArray(changedTagNames) ? changedTagNames : [])
      .map((value) => normalizeTag(value).toLowerCase())
      .filter(Boolean),
  );
  const selectedCount = selectedSet.size;

  return (
    <section className={`ontology-editor-section ${highlighted ? "focused" : ""}`}>
      <div className="ontology-editor-section-head">
        <h4>{title}</h4>
        <div className="ontology-type-section-actions">
          <input
            className="ontology-type-section-search-input"
            value={searchValue}
            onChange={(event) => setSearchValue(event.target.value)}
            placeholder="Search"
            aria-label={`Search ${title}`}
          />
          {!readOnly && selectedCount >= 2 && typeof onMergeSelected === "function" && (
            <button
              type="button"
              className="ontology-type-section-merge-btn"
              onClick={onMergeSelected}
            >
              Merge
            </button>
          )}
          {!readOnly && typeof onToggleRemoveMode === "function" && (
            <button
              type="button"
              className="ontology-type-section-edit-btn"
              onClick={onToggleRemoveMode}
              aria-pressed={removeMode}
            >
              {removeMode ? "Done" : "Edit"}
            </button>
          )}
        </div>
      </div>
      <div className="ontology-tag-editor-box" onClick={() => addInputRef.current?.focus()}>
        {visibleTags.map(({ tag, index }) => (
          <TagChip
            key={`${tag}-${index}`}
            label={tag}
            containerClassName={showRemoveControls ? "ontology-tag-chip-cluster" : ""}
            mainButtonClassName={`ontology-tag-chip ${
              changedSet.has(normalizeTag(tag).toLowerCase()) ? "ontology-tag-chip-changed" : ""
            }`}
            selected={selectedSet.has(index)}
            onClick={(event) => {
              event.stopPropagation();
              if (event.altKey && typeof onToggleSelect === "function") {
                onToggleSelect(index);
                return;
              }
              onOpenProperties(index);
            }}
            {...(showRemoveControls
              ? {
                  onEdit: () => removeTagAt(index),
                  editIcon: "×",
                  editButtonClassName: "ontology-tag-chip-remove",
                  editAriaLabel: `Remove ${String(tag ?? "")}`,
                }
              : {})}
          />
        ))}
        {!readOnly && (
          <input
            ref={addInputRef}
            className="ontology-tag-input"
            value={inputValue}
            onChange={(event) => setInputValue(event.target.value)}
            placeholder={placeholder}
            onBlur={appendTag}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === ",") {
                event.preventDefault();
                appendTag();
                return;
              }
              if (event.key === "Backspace" && !inputValue && tags.length > 0) {
                event.preventDefault();
                removeTagAt(tags.length - 1);
              }
            }}
          />
        )}
      </div>
      {!readOnly && (
        <p className="field-note">
          {removeMode
            ? "Click × to remove a type from the draft (Confirm saves). Click the tag label to edit properties."
            : "Click a tag to edit full properties. Alt+Click toggles multi-select for merge. Press Backspace on empty input to remove the last tag."}
        </p>
      )}
    </section>
  );
}
