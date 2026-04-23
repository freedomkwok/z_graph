#!/usr/bin/env python3
"""
Copyright (c) 2026 Richard G and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Download Langfuse prompts into local label-folder structure.

This module also exposes reusable functions for backend runtime use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from llm_inference_core.prompts.langfuse_sync_policy import LangfuseSyncPolicy

from app.core.langfuse_versioning.zepgraph_langfuse_sync_policy import (
    DEFAULT_ZEPGRAPH_LANGFUSE_SYNC_POLICY,
)
from app.core.langfuse_versioning.zepgraph_langfuse_sync_pull_layout import (
    extract_prompt_items as _extract_prompt_items_from_payload,
)
from app.core.langfuse_versioning.zepgraph_langfuse_sync_pull_layout import (
    extract_prompt_name_for_pull,
    normalize_label,
)

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _merge_normalized_labels(*label_groups: list[str]) -> list[str]:
    merged: list[str] = []
    for labels in label_groups:
        for label in labels:
            normalized = normalize_label(label)
            if normalized and normalized not in merged:
                merged.append(normalized)
    return merged


def _extract_labels_from_prompt_payload(payload: Any) -> list[str]:
    labels: list[str] = []

    def add_label(raw: Any) -> None:
        normalized = normalize_label(str(raw or ""))
        if normalized and normalized not in labels:
            labels.append(normalized)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "labels" in value:
                raw_labels = value.get("labels")
                if isinstance(raw_labels, str):
                    add_label(raw_labels)
                elif isinstance(raw_labels, list):
                    for raw_label in raw_labels:
                        add_label(raw_label)
            if "label" in value:
                add_label(value.get("label"))
            for nested_value in value.values():
                walk(nested_value)
            return
        if isinstance(value, list):
            for nested_value in value:
                walk(nested_value)

    walk(payload)
    return labels


def _resolve_download_labels(
    *,
    available_labels: list[str],
    requested_label: str | None,
    include_all_labels: bool,
) -> list[str | None]:
    if include_all_labels:
        ordered_labels: list[str | None] = []
        if requested_label:
            ordered_labels.append(requested_label)
        for available_label in available_labels:
            if available_label not in ordered_labels:
                ordered_labels.append(available_label)
        if not ordered_labels:
            return [None]
        if (
            requested_label
            and requested_label not in available_labels
            and None not in ordered_labels
        ):
            ordered_labels.append(None)
        return ordered_labels

    if requested_label:
        # Strict mode: when caller requests a label (for example, skillregistry),
        # only fetch that exact label and do not fallback to production/latest.
        return [requested_label]
    if available_labels:
        return available_labels
    return [None]


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


def _fetch_prompt_payload(
    *,
    client: httpx.Client,
    base_url: str,
    prompt_name: str,
    label: str | None,
) -> Any | None:
    encoded_prompt_name = quote(prompt_name, safe="")
    endpoint = f"{base_url.rstrip('/')}/api/public/v2/prompts/{encoded_prompt_name}"
    params: dict[str, str] = {}
    normalized_label = normalize_label(label)
    if normalized_label:
        params["label"] = normalized_label

    response = client.get(endpoint, params=params or None)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _fetch_prompt_text(
    *,
    client: httpx.Client,
    base_url: str,
    prompt_name: str,
    label: str | None,
) -> str | None:
    payload = _fetch_prompt_payload(
        client=client,
        base_url=base_url,
        prompt_name=prompt_name,
        label=label,
    )
    if payload is None:
        return None

    text = _extract_prompt_text(payload)
    if text is None:
        raise ValueError(f"Langfuse prompt payload has no prompt text: {prompt_name}")
    return text


def _list_prompt_items(
    *,
    client: httpx.Client,
    base_url: str,
    limit: int,
    max_pages: int,
    policy: LangfuseSyncPolicy,
) -> list[dict[str, Any]]:
    endpoint = f"{base_url.rstrip('/')}/api/public/v2/prompts"
    collected: list[dict[str, Any]] = []
    unchanged_pages = 0

    for page in range(1, max_pages + 1):
        response = client.get(endpoint, params={"page": page, "limit": limit})
        response.raise_for_status()
        items = _extract_prompt_items_from_payload(response.json(), policy)

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
    include_all_labels: bool = False,
    policy: LangfuseSyncPolicy | None = None,
) -> dict[str, Any]:
    sync_policy = policy or DEFAULT_ZEPGRAPH_LANGFUSE_SYNC_POLICY
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
            policy=sync_policy,
        )

        for item in prompt_items:
            prompt_name = extract_prompt_name_for_pull(item, sync_policy)
            if not prompt_name:
                continue

            prompt_payload = _fetch_prompt_payload(
                client=client,
                base_url=base_url,
                prompt_name=prompt_name,
                label=None,
            )
            payload_labels = _extract_labels_from_prompt_payload(prompt_payload)
            available_labels = _merge_normalized_labels(
                _extract_prompt_labels(item),
                payload_labels,
            )
            download_labels = _resolve_download_labels(
                available_labels=available_labels,
                requested_label=normalized_requested_label,
                include_all_labels=bool(include_all_labels),
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
                    continue
                if prompt_text is None:
                    continue

                target_rel_path = sync_policy.build_pull_target_relative_path(prompt_name, label)
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
        default=DEFAULT_ZEPGRAPH_LANGFUSE_SYNC_POLICY.default_output_relative,
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
    parser.add_argument(
        "--include-all-labels",
        action="store_true",
        help=(
            "When --label is provided, also fetch other available labels for each prompt. "
            "Default behavior is strict label-only download."
        ),
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
            include_all_labels=bool(args.include_all_labels),
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

