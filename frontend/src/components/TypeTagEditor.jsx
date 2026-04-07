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
}) {
  const [inputValue, setInputValue] = useState("");
  const addInputRef = useRef(null);

  useEffect(() => {
    if (!autoFocus) return;
    addInputRef.current?.focus();
  }, [autoFocus]);

  const hasDuplicate = (nextValue) =>
    tags.some((tag) => normalizeTag(tag).toLowerCase() === normalizeTag(nextValue).toLowerCase());

  const appendTag = () => {
    const normalized = normalizeTag(inputValue);
    if (!normalized || hasDuplicate(normalized)) {
      setInputValue("");
      return;
    }
    onChange([...tags, normalized]);
    setInputValue("");
  };

  const removeTagAt = (targetIndex) => {
    onChange(tags.filter((_, index) => index !== targetIndex));
  };

  return (
    <section className={`ontology-editor-section ${highlighted ? "focused" : ""}`}>
      <h4>{title}</h4>
      <div className="ontology-tag-editor-box" onClick={() => addInputRef.current?.focus()}>
        {tags.map((tag, index) => (
          <TagChip
            key={`${tag}-${index}`}
            label={tag}
            mainButtonClassName="ontology-tag-chip"
            onClick={(event) => {
              event.stopPropagation();
              onOpenProperties(index);
            }}
          />
        ))}
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
      </div>
      <p className="field-note">
        Click a tag to edit full properties. Press Backspace on empty input to remove the last tag.
      </p>
    </section>
  );
}
