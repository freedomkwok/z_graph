#!/usr/bin/env python3
"""Download Langfuse prompts into local label-folder structure.

This module also exposes reusable functions for backend runtime use.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = "app/core/langfuse_versioning"
LANGFUSE_LIST_KEYS = ("data", "prompts", "items", "result")
SUPPORTED_CATEGORIES = {"ontology_section", "sub_queries", "fallback_entities"}
LABEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def normalize_label(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _normalize_prompt_name(value: str | None) -> str:
    return str(value or "").strip().strip("/")


def _normalize_category(value: str) -> str:
    return str(value or "").strip().lower()


def _looks_like_label_segment(value: str) -> bool:
    return bool(LABEL_PATTERN.fullmatch(str(value or "").strip().lower()))


def _extract_prompt_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in LANGFUSE_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _extract_prompt_name(item: dict[str, Any]) -> str | None:
    raw_name = item.get("name")
    if not isinstance(raw_name, str):
        return None
    normalized = _normalize_prompt_name(raw_name)
    if not normalized:
        return None
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return None
    category = _normalize_category(parts[0])
    if category not in SUPPORTED_CATEGORIES:
        return None
    if category == "ontology_section":
        if len(parts) < 3 or _normalize_category(parts[1]) not in {"prompts", "labels"}:
            return None
    if ".." in parts:
        return None
    return normalized


def _extract_prompt_labels(item: dict[str, Any]) -> list[str]:
    labels: list[str] = []

    def add_label(raw: Any) -> None:
        normalized = normalize_label(str(raw or ""))
        if normalized and normalized not in labels:
            labels.append(normalized)

    raw_labels = item.get("labels")
    if isinstance(raw_labels, str):
        add_label(raw_labels)
    elif isinstance(raw_labels, list):
        for raw in raw_labels:
            add_label(raw)

    raw_label = item.get("label")
    if raw_label is not None:
        add_label(raw_label)

    return labels


def _resolve_download_labels(
    *,
    available_labels: list[str],
    requested_label: str | None,
) -> list[str | None]:
    if requested_label:
        if requested_label in available_labels:
            return [requested_label]
        if available_labels:
            return available_labels
        return [None]
    if available_labels:
        return available_labels
    return [None]


def _resolve_file_extension(prompt_name: str) -> str:
    category = _normalize_category(prompt_name.split("/", 1)[0])
    if category == "fallback_entities":
        return ".json"
    return ".md"


def _build_target_relative_path(prompt_name: str, label: str | None) -> Path:
    normalized_name = _normalize_prompt_name(prompt_name)
    parts = [part for part in normalized_name.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"Invalid prompt name: {prompt_name}")

    category = _normalize_category(parts[0])
    file_name = parts[-1]
    if "." not in file_name:
        file_name = f"{file_name}{_resolve_file_extension(normalized_name)}"

    normalized_label = normalize_label(label)

    if category == "ontology_section":
        section = _normalize_category(parts[1])
        if section == "prompts":
            relative_parts = ["ontology_section", "prompts"]
            trailing_parts = parts[2:-1]
            if trailing_parts and _looks_like_label_segment(trailing_parts[0]):
                relative_parts.extend(trailing_parts)
            else:
                # Keep production as the default local folder for base ontology prompts.
                relative_parts.append(normalized_label or "production")
                relative_parts.extend(trailing_parts)
            relative_parts.append(file_name)
            return Path(*relative_parts)

        if section == "labels":
            relative_parts = ["ontology_section", "labels"]
            trailing_parts = parts[2:-1]
            if normalized_label:
                relative_parts.append(normalized_label)
                if trailing_parts and _looks_like_label_segment(trailing_parts[0]):
                    trailing_parts = trailing_parts[1:]
            relative_parts.extend(trailing_parts)
            relative_parts.append(file_name)
            return Path(*relative_parts)

        raise ValueError(f"Unsupported ontology_section prompt name: {prompt_name}")

    relative_parts = [_normalize_category(category)]
    trailing_parts = parts[1:-1]

    if normalized_label:
        if trailing_parts and _looks_like_label_segment(trailing_parts[0]):
            trailing_parts = trailing_parts[1:]
        relative_parts.append(normalized_label)

    relative_parts.extend(trailing_parts)
    relative_parts.append(file_name)
    return Path(*relative_parts)


def _format_prompt_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _extract_prompt_text(payload: Any) -> str | None:
    if isinstance(payload, str):
        return payload

    if isinstance(payload, dict):
        for key in ("prompt", "text", "content", "template"):
            if key in payload:
                value = payload.get(key)
                if isinstance(value, (str, dict, list)):
                    return _format_prompt_text(value)

        for key in ("data", "item", "result"):
            if key in payload:
                nested = _extract_prompt_text(payload.get(key))
                if nested:
                    return nested

        versions = payload.get("versions")
        if isinstance(versions, list):
            for version_item in versions:
                nested = _extract_prompt_text(version_item)
                if nested:
                    return nested

        latest_version = payload.get("latestVersion")
        if latest_version is not None:
            nested = _extract_prompt_text(latest_version)
            if nested:
                return nested

    if isinstance(payload, list):
        for item in payload:
            nested = _extract_prompt_text(item)
            if nested:
                return nested

    return None


def _fetch_prompt_text(
    *,
    client: httpx.Client,
    base_url: str,
    prompt_name: str,
    label: str | None,
) -> str:
    encoded_prompt_name = quote(prompt_name, safe="")
    endpoint = f"{base_url.rstrip('/')}/api/public/v2/prompts/{encoded_prompt_name}"
    params: dict[str, str] = {}
    normalized_label = normalize_label(label)
    if normalized_label:
        params["label"] = normalized_label

    response = client.get(endpoint, params=params or None)
    if response.status_code == 404 and params:
        response = client.get(endpoint)
    response.raise_for_status()

    text = _extract_prompt_text(response.json())
    if text is None:
        raise ValueError(f"Langfuse prompt payload has no prompt text: {prompt_name}")
    return text


def _list_prompt_items(
    *,
    client: httpx.Client,
    base_url: str,
    limit: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    endpoint = f"{base_url.rstrip('/')}/api/public/v2/prompts"
    collected: list[dict[str, Any]] = []
    unchanged_pages = 0

    for page in range(1, max_pages + 1):
        response = client.get(endpoint, params={"page": page, "limit": limit})
        response.raise_for_status()
        items = _extract_prompt_items(response.json())

        before_count = len(collected)
        collected.extend(items)
        if not items or len(items) < limit:
            break

        if len(collected) == before_count:
            unchanged_pages += 1
            if unchanged_pages >= 2:
                break
        else:
            unchanged_pages = 0

    return collected


def download_prompts_from_langfuse(
    *,
    output_root: Path,
    public_key: str,
    secret_key: str,
    base_url: str,
    requested_label: str | None = None,
    dry_run: bool = False,
    limit: int = 100,
    max_pages: int = 100,
) -> dict[str, Any]:
    normalized_requested_label = normalize_label(requested_label)
    output_root.mkdir(parents=True, exist_ok=True)

    downloaded_labels: set[str] = set()
    written_files: list[str] = []
    processed_variants: set[tuple[str, str | None]] = set()

    with httpx.Client(auth=(public_key, secret_key), timeout=20.0) as client:
        prompt_items = _list_prompt_items(
            client=client,
            base_url=base_url,
            limit=max(1, limit),
            max_pages=max(1, max_pages),
        )

        for item in prompt_items:
            prompt_name = _extract_prompt_name(item)
            if not prompt_name:
                continue

            available_labels = _extract_prompt_labels(item)
            download_labels = _resolve_download_labels(
                available_labels=available_labels,
                requested_label=normalized_requested_label,
            )

            for label in download_labels:
                variant_key = (prompt_name, label)
                if variant_key in processed_variants:
                    continue
                processed_variants.add(variant_key)

                try:
                    prompt_text = _fetch_prompt_text(
                        client=client,
                        base_url=base_url,
                        prompt_name=prompt_name,
                        label=label,
                    )
                except httpx.HTTPStatusError:
                    if label is None:
                        raise
                    prompt_text = _fetch_prompt_text(
                        client=client,
                        base_url=base_url,
                        prompt_name=prompt_name,
                        label=None,
                    )

                target_rel_path = _build_target_relative_path(prompt_name, label)
                target_abs_path = output_root / target_rel_path
                if not dry_run:
                    target_abs_path.parent.mkdir(parents=True, exist_ok=True)
                    target_abs_path.write_text(prompt_text, encoding="utf-8")

                written_files.append(target_rel_path.as_posix())
                normalized_download_label = normalize_label(label)
                if normalized_download_label:
                    downloaded_labels.add(normalized_download_label)

    return {
        "requested_label": normalized_requested_label,
        "total_prompt_items": len(prompt_items),
        "downloaded_files": len(written_files),
        "downloaded_labels": sorted(downloaded_labels),
        "written_files": sorted(set(written_files)),
        "dry_run": dry_run,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download prompts from Langfuse into local folder structure."
    )
    parser.add_argument(
        "--repo-root",
        default=str(DEFAULT_REPO_ROOT),
        help="Backend repo root path. Defaults to script parent.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Output directory relative to repo root.",
    )
    parser.add_argument(
        "--label",
        default="",
        help=(
            "Preferred label to download. If prompt does not have this label, "
            "the script downloads available label variants."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Page size for prompt listing.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=100,
        help="Maximum pages to scan when listing prompts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview files to be written without writing them.",
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
    load_env_file(repo_root / ".env")
    load_env_file(repo_root / ".env.example")


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    load_default_env(repo_root)

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    base_url = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST") or "http://localhost:3000"
    requested_label = normalize_label(args.label)

    if not public_key or not secret_key:
        print(
            "Missing LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY in environment/.env.",
            file=sys.stderr,
        )
        return 1

    output_root = (repo_root / args.output).resolve()
    if output_root != repo_root and repo_root not in output_root.parents:
        print("Output path must stay inside backend repo root.", file=sys.stderr)
        return 1

    try:
        result = download_prompts_from_langfuse(
            output_root=output_root,
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            requested_label=requested_label,
            dry_run=bool(args.dry_run),
            limit=max(1, int(args.limit)),
            max_pages=max(1, int(args.max_pages)),
        )
    except Exception as exc:
        print(f"Sync from Langfuse failed: {exc}", file=sys.stderr)
        return 2

    action = "Would write" if args.dry_run else "Wrote"
    print(
        f"{action} {result['downloaded_files']} file(s) "
        f"from {result['total_prompt_items']} prompt item(s)."
    )
    if result["downloaded_labels"]:
        print(f"Labels downloaded: {', '.join(result['downloaded_labels'])}")
    for rel_path in result["written_files"]:
        print(f" - {rel_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

