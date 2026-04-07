from __future__ import annotations

PRODUCTION_LABEL = "production"


def normalize_label(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def build_label_fallback_candidates(
    requested_label: str | None,
    default_label: str | None = None,
) -> list[str | None]:
    candidates: list[str | None] = []

    def add_candidate(value: str | None) -> None:
        normalized = normalize_label(value)
        if normalized not in candidates:
            candidates.append(normalized)

    if requested_label is not None:
        add_candidate(requested_label)
    add_candidate(PRODUCTION_LABEL)
    add_candidate(default_label)
    if None not in candidates:
        candidates.append(None)
    return candidates
