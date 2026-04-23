export default function DockSideToggle({
  isRight = false,
  onToggle,
  rightTitle = "Move panel to left",
  leftTitle = "Move panel to right",
  className = "",
  buttonClassName = "",
  onMouseDown,
}) {
  const title = isRight ? rightTitle : leftTitle;
  const arrow = isRight ? "<-" : "->";
  const combinedClassName = [className, buttonClassName].filter(Boolean).join(" ");

  return (
    <button
      className={combinedClassName || undefined}
      type="button"
      onClick={onToggle}
      onMouseDown={onMouseDown}
      title={title}
      aria-label={title}
    >
      {arrow}
    </button>
  );
}
