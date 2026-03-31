import { useEffect, useRef, useState } from "react";

export default function EditableStringListEditor({
  values = [],
  onChange,
  placeholder = "",
  disabled = false,
  listClassName = "ontology-string-list",
  chipClassName = "ontology-string-chip",
  chipMarkerClassName = "ontology-string-chip-marker",
  inputClassName = "ontology-string-input",
  editInputClassName = "ontology-string-edit-input",
  showEditTools = false,
}) {
  const toText = (value) => String(value ?? "").trim();
  const [inputValue, setInputValue] = useState("");
  const [editingIndex, setEditingIndex] = useState(-1);
  const [editingValue, setEditingValue] = useState("");
  const [showDeleteControls, setShowDeleteControls] = useState(false);
  const addInputRef = useRef(null);
  const editInputRef = useRef(null);
  const commitLockRef = useRef(false);
  const normalizedValues = (Array.isArray(values) ? values : [])
    .map((value) => toText(value))
    .filter(Boolean);
  const canShowDeleteControls = showDeleteControls && editingIndex < 0;

  useEffect(() => {
    if (editingIndex < 0) return;
    editInputRef.current?.focus();
    editInputRef.current?.select();
  }, [editingIndex]);

  useEffect(() => {
    if (showEditTools || !showDeleteControls) return;
    setShowDeleteControls(false);
  }, [showDeleteControls, showEditTools]);

  const hasDuplicate = (nextValue, excludedIndex = -1) =>
    normalizedValues.some(
      (item, index) =>
        index !== excludedIndex &&
        String(item ?? "").trim().toLowerCase() === String(nextValue ?? "").trim().toLowerCase(),
    );

  const appendValue = () => {
    if (disabled) return;
    const normalized = toText(inputValue);
    if (!normalized || hasDuplicate(normalized)) {
      setInputValue("");
      return;
    }
    onChange([...normalizedValues, normalized]);
    setInputValue("");
  };

  const removeValueAt = (targetIndex) => {
    if (disabled) return;
    onChange(normalizedValues.filter((_, index) => index !== targetIndex));
  };

  const beginEdit = (targetIndex) => {
    if (disabled) return;
    if (targetIndex < 0 || targetIndex >= normalizedValues.length) return;
    commitLockRef.current = false;
    setEditingIndex(targetIndex);
    setEditingValue(toText(normalizedValues[targetIndex]));
  };

  const commitEdit = () => {
    if (disabled || editingIndex < 0 || commitLockRef.current) return;
    commitLockRef.current = true;
    const targetIndex = editingIndex;
    const normalized = toText(editingValue);
    setEditingIndex(-1);
    setEditingValue("");

    if (targetIndex >= normalizedValues.length) {
      setTimeout(() => {
        commitLockRef.current = false;
      }, 0);
      return;
    }

    if (!normalized) {
      removeValueAt(targetIndex);
    } else if (!hasDuplicate(normalized, targetIndex)) {
      const nextValues = [...normalizedValues];
      nextValues[targetIndex] = normalized;
      onChange(nextValues);
    }

    setTimeout(() => {
      commitLockRef.current = false;
    }, 0);
  };

  return (
    <div className={listClassName} onClick={() => !disabled && addInputRef.current?.focus()}>
      {showEditTools && (
        <div
          className="ontology-string-list-toolbar"
          onClick={(event) => {
            event.stopPropagation();
          }}
        >
          <button
            className="ontology-string-edit-mode-btn"
            type="button"
            onMouseDown={(event) => {
              event.preventDefault();
            }}
            onClick={(event) => {
              event.stopPropagation();
              if (disabled) return;
              setShowDeleteControls((current) => !current);
            }}
            disabled={disabled || normalizedValues.length === 0 || editingIndex >= 0}
            title={showDeleteControls ? "Hide delete actions" : "Show delete actions"}
          >
            {showDeleteControls ? "Done" : "Edit"}
          </button>
        </div>
      )}
      {normalizedValues.map((value, index) =>
        editingIndex === index ? (
          <input
            key={`edit-${index}-${value}`}
            ref={editInputRef}
            className={editInputClassName}
            value={toText(editingValue)}
            onChange={(event) => setEditingValue(event.target.value)}
            onBlur={commitEdit}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                event.currentTarget.blur();
              } else if (event.key === "Escape") {
                event.preventDefault();
                commitLockRef.current = true;
                setEditingIndex(-1);
                setEditingValue("");
                setTimeout(() => {
                  commitLockRef.current = false;
                }, 0);
              }
            }}
            disabled={disabled}
          />
        ) : (
          <div className="ontology-string-list-item" key={`item-${index}-${value}`}>
            <button
              className={chipClassName}
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
              }}
              onClick={(event) => {
                event.stopPropagation();
                beginEdit(index);
              }}
              disabled={disabled}
            >
              <span className={chipMarkerClassName} aria-hidden="true" />
              <span>{toText(value)}</span>
            </button>
            {canShowDeleteControls && (
              <button
                className="ontology-string-delete-btn"
                type="button"
                onMouseDown={(event) => {
                  event.preventDefault();
                }}
                onClick={(event) => {
                  event.stopPropagation();
                  removeValueAt(index);
                }}
                disabled={disabled}
                title={`Delete ${toText(value)}`}
              >
                Delete
              </button>
            )}
          </div>
        ),
      )}
      <input
        ref={addInputRef}
        className={inputClassName}
        value={inputValue}
        onChange={(event) => setInputValue(event.target.value)}
        placeholder={placeholder}
        onBlur={() => {
          setInputValue((current) => String(current ?? "").trim());
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            appendValue();
            return;
          }
          if (event.key === "Backspace" && !inputValue && normalizedValues.length > 0) {
            event.preventDefault();
            removeValueAt(normalizedValues.length - 1);
          }
        }}
        disabled={disabled}
      />
    </div>
  );
}
