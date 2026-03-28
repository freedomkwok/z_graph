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
}) {
  const [inputValue, setInputValue] = useState("");
  const [editingIndex, setEditingIndex] = useState(-1);
  const [editingValue, setEditingValue] = useState("");
  const addInputRef = useRef(null);
  const editInputRef = useRef(null);
  const normalizedValues = Array.isArray(values) ? values : [];

  useEffect(() => {
    if (editingIndex < 0) return;
    editInputRef.current?.focus();
    editInputRef.current?.select();
  }, [editingIndex]);

  const hasDuplicate = (nextValue, excludedIndex = -1) =>
    normalizedValues.some(
      (item, index) =>
        index !== excludedIndex &&
        String(item ?? "").trim().toLowerCase() === String(nextValue ?? "").trim().toLowerCase(),
    );

  const appendValue = () => {
    if (disabled) return;
    const normalized = String(inputValue ?? "").trim();
    if (!normalized || hasDuplicate(normalized)) {
      setInputValue("");
      return;
    }
    onChange([...(Array.isArray(values) ? values : []), normalized]);
    setInputValue("");
  };

  const removeValueAt = (targetIndex) => {
    if (disabled) return;
    onChange(normalizedValues.filter((_, index) => index !== targetIndex));
  };

  const beginEdit = (targetIndex) => {
    if (disabled) return;
    setEditingIndex(targetIndex);
    setEditingValue(normalizedValues[targetIndex] ?? "");
  };

  const commitEdit = () => {
    if (disabled || editingIndex < 0) return;
    const normalized = String(editingValue ?? "").trim();
    if (!normalized) {
      removeValueAt(editingIndex);
    } else if (!hasDuplicate(normalized, editingIndex)) {
      const nextValues = [...normalizedValues];
      nextValues[editingIndex] = normalized;
      onChange(nextValues);
    }
    setEditingIndex(-1);
    setEditingValue("");
  };

  return (
    <div className={listClassName} onClick={() => !disabled && addInputRef.current?.focus()}>
      {normalizedValues.map((value, index) =>
        editingIndex === index ? (
          <input
            key={`${value}-${index}`}
            ref={editInputRef}
            className={editInputClassName}
            value={editingValue}
            onChange={(event) => setEditingValue(event.target.value)}
            onBlur={commitEdit}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitEdit();
              } else if (event.key === "Escape") {
                event.preventDefault();
                setEditingIndex(-1);
                setEditingValue("");
              }
            }}
            disabled={disabled}
          />
        ) : (
          <button
            key={`${value}-${index}`}
            className={chipClassName}
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              beginEdit(index);
            }}
            disabled={disabled}
          >
            <span className={chipMarkerClassName} aria-hidden="true" />
            <span>{value}</span>
          </button>
        ),
      )}
      <input
        ref={addInputRef}
        className={inputClassName}
        value={inputValue}
        onChange={(event) => setInputValue(event.target.value)}
        placeholder={placeholder}
        onBlur={appendValue}
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
