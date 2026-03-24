#!/usr/bin/env python3
"""Sync markdown prompts into Langfuse for backend prompt directories."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import httpx


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = (
    "app/core/langfuse_versioning/prompts",
    "app/core/langfuse_versioning/sub_queries",
    # Support current folder name and corrected spelling.
    "app/core/langfuse_versioning/fallback_entites",
    "app/core/langfuse_versioning/fallback_entities",
)
LANGFUSE_PROMPT_REF_RE = re.compile(r"@@@langfusePrompt:([^@]+)@@@")


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
            "Can be passed multiple times. Defaults to langfuse_versioning prompts + sub_queries."
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


def _normalize_source_prefixes(sources: Iterable[str]) -> list[str]:
    prefixes: list[str] = []
    for source in sources:
        prefix = source.strip().strip("/")
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def _normalize_folder_aliases(name: str) -> str:
    # Normalize historical typo to stable server-side path.
    return name.replace("fallback_entites/", "fallback_entities/")


def _structured_prompt_name(relative_file_path: Path, sources: Iterable[str]) -> str:
    no_ext = relative_file_path.as_posix()
    langfuse_root = "app/core/langfuse_versioning/"
    if no_ext.startswith(langfuse_root):
        no_ext = no_ext[len(langfuse_root) :]
    else:
        source_prefixes = _normalize_source_prefixes(sources)
        for source_prefix in source_prefixes:
            if no_ext.startswith(f"{source_prefix}/"):
                no_ext = no_ext[len(source_prefix) + 1 :]
                break

    no_ext = _normalize_folder_aliases(no_ext)
    if no_ext.endswith(".md"):
        no_ext = no_ext[:-3]
    return re.sub(r"/{2,}", "/", no_ext).strip("/")


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


def _legacy_prompt_name(relative_file_path: Path, sources: Iterable[str]) -> str:
    # Previous behavior: flatten source path and keep only file-level name.
    no_ext = relative_file_path.as_posix()
    source_prefixes = _normalize_source_prefixes(sources)
    for source_prefix in source_prefixes:
        if no_ext.startswith(f"{source_prefix}/"):
            no_ext = no_ext[len(source_prefix) + 1 :]
            break
    if no_ext.endswith(".md"):
        no_ext = no_ext[:-3]
    return re.sub(r"/{2,}", "/", no_ext).strip("/")


def iter_prompt_files(repo_root: Path, sources: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for source in sources:
        source_path = (repo_root / source).resolve()
        if not source_path.exists() or not source_path.is_dir():
            continue
        files.extend(sorted(source_path.rglob("*.md")))
        files.extend(sorted(source_path.rglob("*.json")))
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
    alias_map: dict[str, str] = {}
    deps_map: dict[str, set[str]] = {}

    # Build maps for canonical prompt name -> file path.
    for file_path in prompt_files:
        rel = file_path.relative_to(repo_root)
        canonical = normalize_prompt_name(rel, name_prefix, sources)
        structured = _structured_prompt_name(rel, sources)
        flat_alias = _flat_prompt_alias(rel)
        legacy_alias = _legacy_prompt_name(rel, sources)
        existing = rel_map.get(canonical)
        if existing is not None and existing != file_path:
            raise ValueError(
                f"Duplicate prompt name '{canonical}' for "
                f"{existing.relative_to(repo_root)} and {rel}"
            )

        rel_map[canonical] = file_path
        alias_map[canonical] = canonical
        alias_map[structured] = canonical
        alias_map[flat_alias] = canonical
        alias_map[legacy_alias] = canonical

        # Accept both folder spellings during dependency resolution.
        if "fallback_entities/" in structured:
            alias_map[structured.replace("fallback_entities/", "fallback_entites/")] = canonical

    missing_refs: set[str] = set()
    # Read dependencies and resolve aliases.
    for canonical, file_path in rel_map.items():
        content = file_path.read_text(encoding="utf-8")
        raw_deps = extract_prompt_dependencies(content)
        resolved: set[str] = set()
        for dep in raw_deps:
            dep_canonical = alias_map.get(dep)
            if dep_canonical is None:
                missing_refs.add(dep)
                continue
            if dep_canonical != canonical:
                resolved.add(dep_canonical)
        deps_map[canonical] = resolved

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


def create_or_update_prompt(
    *,
    client: httpx.Client,
    base_url: str,
    payload: dict,
) -> tuple[bool, str]:
    endpoint = f"{base_url.rstrip('/')}/api/public/v2/prompts"
    response = client.post(endpoint, json=payload)
    if response.status_code in (200, 201):
        return True, "created"
    if response.status_code == 409:
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
            print(f"[DRY-RUN] {rel.as_posix()} -> {name}")
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

            payload = build_payload(
                name=prompt_name,
                content=content,
                labels=labels,
                source_path=rel.as_posix(),
            )

            success, info = create_or_update_prompt(
                client=client,
                base_url=base_url,
                payload=payload,
            )
            if success:
                ok += 1
                print(f"[OK] {rel.as_posix()} -> {prompt_name} ({info})")
            else:
                failed += 1
                print(
                    f"[FAIL] {rel.as_posix()} -> {prompt_name} ({info})",
                    file=sys.stderr,
                )

    print(f"Finished. success={ok} failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
