function joinClasses(...values) {
  return values.filter(Boolean).join(" ");
}

export default function TagChip({
  label,
  onClick,
  onEdit,
  selected = false,
  disabled = false,
  title = "",
  containerClassName = "",
  mainButtonClassName = "ontology-tag-chip",
  editButtonClassName = "",
  editIcon = "✎",
  editAriaLabel = "",
}) {
  const resolvedTitle = title || String(label ?? "");
  const resolvedEditAriaLabel = editAriaLabel || `Edit ${String(label ?? "")}`;

  if (typeof onEdit === "function") {
    return (
      <div
        className={joinClasses(
          containerClassName,
          selected && "selected",
          disabled && "disabled",
        )}
      >
        <button
          type="button"
          className={joinClasses(mainButtonClassName, selected && "selected")}
          onClick={onClick}
          disabled={disabled}
          title={resolvedTitle}
        >
          {label}
        </button>
        <button
          type="button"
          className={editButtonClassName}
          onClick={(event) => {
            event.stopPropagation();
            onEdit();
          }}
          disabled={disabled}
          aria-label={resolvedEditAriaLabel}
          title={resolvedEditAriaLabel}
        >
          {editIcon}
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      className={joinClasses(mainButtonClassName, selected && "selected")}
      onClick={onClick}
      disabled={disabled}
      title={resolvedTitle}
    >
      {label}
    </button>
  );
}
