#!/usr/bin/env python3
"""Sync markdown prompts into Langfuse for backend prompt directories."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import quote

import httpx

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = (
    "app/core/langfuse_versioning/ontology_section",
    "app/core/langfuse_versioning/sub_queries",
    "app/core/langfuse_versioning/fallback_entities",
    "app/core/langfuse_versioning/auto_label_generator",
)
LANGFUSE_PROMPT_REF_RE = re.compile(r"@@@langfusePrompt:([^@]+)@@@")
LABEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
PROMPT_STEM_ALIASES = {
    "relations_in_system_prompt copy": "RELATIONS_IN_SYSTEM_PROMPT",
}
SYNC_PATH_ALLOWLIST = (
    re.compile(r"^ontology_section/prompts/[^/]+/[^/]+\.(md|json)$"),
    re.compile(r"^ontology_section/labels/[^/]+/[^/]+\.(md|json)$"),
    re.compile(r"^sub_queries/.+\.(md|json)$"),
    re.compile(r"^fallback_entities/.+\.(md|json)$"),
    # Label-structured prompt folders.
    # Example: auto_label_generator/prompts/production/ENTITY_EDGE_GENERATOR.md
    re.compile(r"^auto_label_generator/prompts/[^/]+/.+\.(md|json)$"),
    re.compile(r"^auto_label_generator/labels/[^/]+/.+\.(md|json)$"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync prompt markdown files to Langfuse.")
    parser.add_argument(
        "--repo-root",
        default=str(DEFAULT_REPO_ROOT),
        help="Backend repo root path. Defaults to script parent.",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help=(
            "Source directory to scan for .md files. "
            "Can be passed multiple times. Defaults to "
            "ontology_section + sub_queries + fallback_entities + auto_label_generator."
        ),
    )
    parser.add_argument(
        "--name-prefix",
        default="",
        help="Optional prefix to prepend to each Langfuse prompt name.",
    )
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        help="Optional Langfuse label(s), can be passed multiple times.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be uploaded without calling Langfuse API.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help=(
            "Delete existing prompts (all versions) before upload, "
            "so uploaded prompt starts from version 1."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation for destructive operations.",
    )
    return parser.parse_args()


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_default_env(repo_root: Path) -> None:
    # Keep existing env priority; only fill missing values from files.
    load_env_file(repo_root / ".env")
    load_env_file(repo_root / ".env.example")


def normalize_label(label: str) -> str:
    # Langfuse label pattern: lowercase alphanumeric plus _, -, .
    return label.strip().lower()


def _merge_labels(*label_groups: Iterable[str]) -> list[str]:
    merged: list[str] = []
    for group in label_groups:
        for label in group:
            normalized = normalize_label(str(label or ""))
            if normalized and normalized not in merged:
                merged.append(normalized)
    return merged


def _infer_labels_from_file_path(relative_file_path: Path, sources: Iterable[str]) -> list[str]:
    raw_relative = _relative_path_without_source_prefix(relative_file_path, sources)
    parts = [part for part in raw_relative.split("/") if part]

    # Local structure:
    #   ontology_section/prompts/<label>/<PROMPT_NAME>
    # Upload keeps this folder order.
    if len(parts) >= 4 and parts[0] == "ontology_section" and parts[1] == "prompts":
        label_candidate = normalize_label(parts[2])
        if not LABEL_PATTERN.fullmatch(label_candidate):
            return []
        return [label_candidate]

    # Local structure:
    #   ontology_section/labels/<label>/<PROMPT_NAME>
    # Upload structure:
    #   ontology_section/labels/<PROMPT_NAME> with Langfuse label=<label>.
    if len(parts) >= 4 and parts[0] == "ontology_section" and parts[1] == "labels":
        label_candidate = normalize_label(parts[2])
        if not LABEL_PATTERN.fullmatch(label_candidate):
            return []
        return [label_candidate]

    if len(parts) < 3:
        return []

    root_category = parts[0]
    if root_category in {"sub_queries", "fallback_entities"}:
        label_candidate = normalize_label(parts[1])
        if not LABEL_PATTERN.fullmatch(label_candidate):
            return []
        return [label_candidate]

    # auto_label_generator follows:
    #   auto_label_generator/prompts/<label>/<PROMPT_NAME>
    #   auto_label_generator/labels/<label>/<PROMPT_NAME>
    if (
        root_category == "auto_label_generator"
        and len(parts) >= 4
        and parts[1] in {"prompts", "labels"}
    ):
        label_candidate = normalize_label(parts[2])
        if not LABEL_PATTERN.fullmatch(label_candidate):
            return []
        return [label_candidate]

    return []


def _normalize_source_prefixes(sources: Iterable[str]) -> list[str]:
    prefixes: list[str] = []
    for source in sources:
        prefix = source.strip().strip("/")
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def _relative_path_without_source_prefix(relative_file_path: Path, sources: Iterable[str]) -> str:
    raw_path = relative_file_path.as_posix()
    langfuse_root = "app/core/langfuse_versioning/"
    if raw_path.startswith(langfuse_root):
        return raw_path[len(langfuse_root) :]

    source_prefixes = _normalize_source_prefixes(sources)
    for source_prefix in source_prefixes:
        if raw_path.startswith(f"{source_prefix}/"):
            return raw_path[len(source_prefix) + 1 :]
    return raw_path


def _normalize_folder_aliases(name: str) -> str:
    # Drop local label folder from ontology_section prompt names.
    # Keep Langfuse naming canonical:
    # - ontology_section/prompts/<PROMPT_NAME> (labels in Langfuse metadata)
    # - ontology_section/labels/<PROMPT_NAME> (labels in Langfuse metadata)
    parts = [part for part in str(name or "").split("/") if part]
    if len(parts) >= 4 and parts[0] == "ontology_section" and parts[1] == "prompts":
        return "/".join(["ontology_section", "prompts", *parts[3:]])
    if len(parts) >= 4 and parts[0] == "ontology_section" and parts[1] == "labels":
        return "/".join(["ontology_section", "labels", *parts[3:]])
    return name


def _normalize_prompt_stem_alias(stem: str) -> str:
    normalized = str(stem or "").strip()
    if not normalized:
        return normalized
    alias = PROMPT_STEM_ALIASES.get(normalized.lower())
    if alias:
        return alias
    return normalized


def _apply_prompt_leaf_alias(prompt_name: str) -> str:
    parts = [part for part in str(prompt_name or "").split("/") if part]
    if not parts:
        return ""
    parts[-1] = _normalize_prompt_stem_alias(parts[-1])
    return "/".join(parts)


def _structured_prompt_name(relative_file_path: Path, sources: Iterable[str]) -> str:
    no_ext = _relative_path_without_source_prefix(relative_file_path, sources)

    no_ext = _normalize_folder_aliases(no_ext)
    if no_ext.endswith(".md"):
        no_ext = no_ext[:-3]
    no_ext = _apply_prompt_leaf_alias(no_ext)
    return re.sub(r"/{2,}", "/", no_ext).strip("/")


def _is_legacy_copy_file(path: Path) -> bool:
    return str(path.stem or "").strip().lower().endswith(" copy")


def _flat_prompt_alias(relative_file_path: Path) -> str:
    filename = relative_file_path.name
    if filename.endswith(".md"):
        return filename[:-3]
    return filename


def normalize_prompt_name(relative_file_path: Path, prefix: str, sources: Iterable[str]) -> str:
    name = _structured_prompt_name(relative_file_path, sources)
    if prefix:
        return f"{prefix.strip('/')}/{name}"
    return name


def _build_prompt_variant_key(relative_file_path: Path, prefix: str, sources: Iterable[str]) -> str:
    canonical_name = normalize_prompt_name(relative_file_path, prefix, sources)
    inferred_labels = _infer_labels_from_file_path(relative_file_path, sources)
    labels_key = ",".join(inferred_labels) if inferred_labels else "-"
    return f"{canonical_name}@@labels={labels_key}"


def _legacy_prompt_name(relative_file_path: Path, sources: Iterable[str]) -> str:
    # Previous behavior: flatten source path and keep only file-level name.
    no_ext = _relative_path_without_source_prefix(relative_file_path, sources)
    if no_ext.endswith(".md"):
        no_ext = no_ext[:-3]
    return re.sub(r"/{2,}", "/", no_ext).strip("/")


def _is_sync_allowed(relative_file_path: Path, sources: Iterable[str]) -> bool:
    normalized = _relative_path_without_source_prefix(relative_file_path, sources)
    normalized = re.sub(r"/{2,}", "/", normalized).strip("/")
    return any(pattern.fullmatch(normalized) for pattern in SYNC_PATH_ALLOWLIST)


def iter_prompt_files(repo_root: Path, sources: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for source in sources:
        source_path = (repo_root / source).resolve()
        if not source_path.exists() or not source_path.is_dir():
            continue
        for file_path in sorted(source_path.rglob("*.md")):
            rel = file_path.relative_to(repo_root)
            if _is_sync_allowed(rel, sources):
                files.append(file_path)
        for file_path in sorted(source_path.rglob("*.json")):
            rel = file_path.relative_to(repo_root)
            if _is_sync_allowed(rel, sources):
                files.append(file_path)
    return files


def extract_prompt_dependencies(content: str) -> set[str]:
    deps: set[str] = set()
    for match in LANGFUSE_PROMPT_REF_RE.findall(content):
        parts = [part.strip() for part in match.split("|") if part.strip()]
        for part in parts:
            if part.startswith("name="):
                dep_name = part.split("=", 1)[1].strip().strip("/")
                if dep_name:
                    deps.add(dep_name)
    return deps


def order_prompt_files_by_dependency(
    *,
    repo_root: Path,
    prompt_files: list[Path],
    sources: Iterable[str],
    name_prefix: str,
) -> tuple[list[Path], list[str]]:
    rel_map: dict[str, Path] = {}
    variant_to_canonical: dict[str, str] = {}
    alias_map: dict[str, str] = {}
    deps_map: dict[str, set[str]] = {}

    # Build maps for prompt variant -> file path. Label variants may intentionally
    # share the same canonical prompt name (for example, ontology_section/labels/*).
    for file_path in prompt_files:
        rel = file_path.relative_to(repo_root)
        canonical = normalize_prompt_name(rel, name_prefix, sources)
        variant_key = _build_prompt_variant_key(rel, name_prefix, sources)
        structured = _structured_prompt_name(rel, sources)
        flat_alias = _flat_prompt_alias(rel)
        legacy_alias = _legacy_prompt_name(rel, sources)
        existing = rel_map.get(variant_key)
        if existing is not None and existing != file_path:
            # Prefer canonical file names over legacy "... copy.*" aliases.
            if _is_legacy_copy_file(existing) and not _is_legacy_copy_file(file_path):
                rel_map[variant_key] = file_path
                variant_to_canonical[variant_key] = canonical
            elif not _is_legacy_copy_file(existing) and _is_legacy_copy_file(file_path):
                continue
            else:
                raise ValueError(
                    f"Duplicate prompt variant '{variant_key}' for "
                    f"{existing.relative_to(repo_root)} and {rel}"
                )
        else:
            rel_map[variant_key] = file_path
            variant_to_canonical[variant_key] = canonical

        alias_map.setdefault(canonical, variant_key)
        alias_map.setdefault(structured, variant_key)
        alias_map.setdefault(flat_alias, variant_key)
        alias_map.setdefault(legacy_alias, variant_key)

    missing_refs: set[str] = set()
    # Read dependencies and resolve aliases.
    for variant_key, file_path in rel_map.items():
        content = file_path.read_text(encoding="utf-8")
        raw_deps = extract_prompt_dependencies(content)
        resolved: set[str] = set()
        for dep in raw_deps:
            dep_variant = alias_map.get(dep)
            if dep_variant is None:
                missing_refs.add(dep)
                continue
            if dep_variant != variant_key:
                resolved.add(dep_variant)
        deps_map[variant_key] = resolved

    # Kahn topological sort (dependencies first).
    reverse_edges: dict[str, set[str]] = {name: set() for name in rel_map}
    indegree: dict[str, int] = {name: 0 for name in rel_map}
    for name, deps in deps_map.items():
        indegree[name] = len(deps)
        for dep in deps:
            reverse_edges[dep].add(name)

    ready = sorted([name for name, degree in indegree.items() if degree == 0])
    ordered_names: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered_names.append(current)
        for dependent in sorted(reverse_edges[current]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
        ready.sort()

    if len(ordered_names) != len(rel_map):
        unresolved = sorted([name for name, degree in indegree.items() if degree > 0])
        raise ValueError(
            "Cyclic prompt dependency detected among: " + ", ".join(unresolved)
        )

    ordered_files = [rel_map[name] for name in ordered_names]
    return ordered_files, sorted(missing_refs)


def build_payload(
    *,
    name: str,
    content: str,
    labels: list[str],
    source_path: str,
) -> dict:
    payload = {
        "name": name,
        "type": "text",
        "prompt": content,
        "config": {"sourcePath": source_path},
    }
    if labels:
        payload["labels"] = labels
    return payload


def _resolve_primary_label(payload: dict) -> str | None:
    raw_labels = payload.get("labels")
    if isinstance(raw_labels, list):
        for raw_label in raw_labels:
            normalized = normalize_label(str(raw_label or ""))
            if normalized:
                return normalized
    return None


def prompt_exists(
    *,
    client: httpx.Client,
    base_url: str,
    prompt_name: str,
    label: str | None,
) -> bool:
    endpoint = f"{base_url.rstrip('/')}/api/public/v2/prompts/{quote(prompt_name, safe='')}"
    params = {"label": label} if label else None
    response = client.get(endpoint, params=params)
    if response.status_code == 404 and label:
        response = client.get(endpoint)
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return True


def create_or_update_prompt(
    *,
    client: httpx.Client,
    base_url: str,
    payload: dict,
) -> tuple[bool, str]:
    prompt_name = str(payload.get("name") or "").strip()
    if not prompt_name:
        return False, "payload.name is required"

    primary_label = _resolve_primary_label(payload)
    existed_before_upload = prompt_exists(
        client=client,
        base_url=base_url,
        prompt_name=prompt_name,
        label=primary_label,
    )

    endpoint = f"{base_url.rstrip('/')}/api/public/v2/prompts"
    response = client.post(endpoint, json=payload)
    if response.status_code in (200, 201):
        if existed_before_upload:
            return True, "updated"
        return True, "created"
    if response.status_code == 409:
        if existed_before_upload:
            return True, "unchanged"
        return True, "exists"

    return False, f"{response.status_code} {response.text[:240]}"


def delete_prompt_all_versions(
    *,
    client: httpx.Client,
    base_url: str,
    prompt_name: str,
) -> tuple[bool, str]:
    encoded = quote(prompt_name, safe="")
    endpoint = f"{base_url.rstrip('/')}/api/public/v2/prompts/{encoded}"
    response = client.delete(endpoint)
    if response.status_code in (200, 202, 204, 404):
        return True, "deleted"
    return False, f"{response.status_code} {response.text[:240]}"


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    load_default_env(repo_root)

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    base_url = (
        os.getenv("LANGFUSE_BASE_URL")
        or os.getenv("LANGFUSE_HOST")
        or "http://localhost:3000"
    )
    labels = [normalize_label(label) for label in args.label if label and label.strip()]

    if not public_key or not secret_key:
        print(
            "Missing LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY in environment/.env.",
            file=sys.stderr,
        )
        return 1

    sources = args.source or list(DEFAULT_SOURCES)
    prompt_files = iter_prompt_files(repo_root, sources)
    if not prompt_files:
        print("No markdown prompt files found in configured sources.")
        return 0

    try:
        prompt_files, missing_refs = order_prompt_files_by_dependency(
            repo_root=repo_root,
            prompt_files=prompt_files,
            sources=sources,
            name_prefix=args.name_prefix,
        )
    except ValueError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2

    print(f"Discovered {len(prompt_files)} prompt files.")
    if missing_refs:
        print(
            "Warning: prompt references not found locally "
            f"(treated as external): {', '.join(missing_refs)}",
            file=sys.stderr,
        )
    if args.clean and not args.yes:
        print(
            "WARNING: --clean will DELETE existing prompts and all versions before upload.",
            file=sys.stderr,
        )
        confirm = input("Type YES/yes/y to continue: ").strip().lower()
        if confirm not in {"yes", "y"}:
            print("Aborted.")
            return 1

    if args.dry_run:
        for file_path in prompt_files:
            rel = file_path.relative_to(repo_root)
            name = normalize_prompt_name(rel, args.name_prefix, sources)
            inferred_labels = _infer_labels_from_file_path(rel, sources)
            final_labels = _merge_labels(inferred_labels, labels)
            labels_repr = ",".join(final_labels) if final_labels else "-"
            print(f"[DRY-RUN] {rel.as_posix()} -> {name} [labels={labels_repr}]")
            if args.clean:
                print(f"[DRY-RUN] delete all versions -> {name}")
        return 0

    ok = 0
    failed = 0
    with httpx.Client(auth=(public_key, secret_key), timeout=20.0) as client:
        if args.clean:
            print("Phase 1/2: deleting all prompt versions...")
            for file_path in prompt_files:
                rel = file_path.relative_to(repo_root)
                prompt_name = normalize_prompt_name(rel, args.name_prefix, sources)
                deleted, delete_info = delete_prompt_all_versions(
                    client=client,
                    base_url=base_url,
                    prompt_name=prompt_name,
                )
                if deleted:
                    print(f"[OK] {rel.as_posix()} -> {prompt_name} (deleted)")
                else:
                    failed += 1
                    print(
                        f"[FAIL] {rel.as_posix()} -> {prompt_name} (delete failed: {delete_info})",
                        file=sys.stderr,
                    )

            if failed > 0:
                print(
                    f"Abort upload due to delete failures. failed={failed}",
                    file=sys.stderr,
                )
                return 2

            print("Phase 2/2: recreating prompts...")

        for file_path in prompt_files:
            rel = file_path.relative_to(repo_root)
            prompt_name = normalize_prompt_name(rel, args.name_prefix, sources)
            content = file_path.read_text(encoding="utf-8")
            inferred_labels = _infer_labels_from_file_path(rel, sources)
            final_labels = _merge_labels(inferred_labels, labels)

            payload = build_payload(
                name=prompt_name,
                content=content,
                labels=final_labels,
                source_path=rel.as_posix(),
            )

            success, info = create_or_update_prompt(
                client=client,
                base_url=base_url,
                payload=payload,
            )
            labels_repr = ",".join(final_labels) if final_labels else "-"
            if success:
                ok += 1
                print(f"[OK][{info}] {rel.as_posix()} -> {prompt_name} [labels={labels_repr}]")
            else:
                failed += 1
                print(
                    f"[FAIL] {rel.as_posix()} -> {prompt_name} [labels={labels_repr}] ({info})",
                    file=sys.stderr,
                )

    print(f"Finished. success={ok} failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
