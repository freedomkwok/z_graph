#!/usr/bin/env python3
"""Delete all prompts from a Langfuse server."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import quote

import httpx


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete all prompts from Langfuse.")
    parser.add_argument(
        "--repo-root",
        default=str(DEFAULT_REPO_ROOT),
        help="Backend repo root path. Defaults to script parent.",
    )
    parser.add_argument(
        "--name-prefix",
        default="",
        help="Optional prompt name prefix filter. Only matching prompts are deleted.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Page size when listing prompts.",
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
        help="Print prompts that would be deleted without deleting.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation.",
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


def _extract_prompt_names(payload: object) -> list[str]:
    items: list[object]
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        candidates = (
            payload.get("data"),
            payload.get("prompts"),
            payload.get("items"),
            payload.get("result"),
        )
        items = next((entry for entry in candidates if isinstance(entry, list)), [])
    else:
        items = []

    names: list[str] = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    return names


def list_prompt_names(
    *,
    client: httpx.Client,
    base_url: str,
    limit: int,
    max_pages: int,
    name_prefix: str,
) -> list[str]:
    endpoint = f"{base_url.rstrip('/')}/api/public/v2/prompts"
    prefix = name_prefix.strip().strip("/")
    collected: set[str] = set()
    unchanged_pages = 0

    for page in range(1, max_pages + 1):
        response = client.get(endpoint, params={"page": page, "limit": limit})
        response.raise_for_status()
        payload = response.json()
        page_names = _extract_prompt_names(payload)

        before = len(collected)
        for name in page_names:
            if prefix and not name.startswith(prefix):
                continue
            collected.add(name)

        if not page_names:
            break
        if len(page_names) < limit:
            break

        if len(collected) == before:
            unchanged_pages += 1
            if unchanged_pages >= 2:
                # Some servers ignore page param; avoid infinite repetition.
                break
        else:
            unchanged_pages = 0

    return sorted(collected)


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

    if not public_key or not secret_key:
        print(
            "Missing LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY in environment/.env.",
            file=sys.stderr,
        )
        return 1

    try:
        with httpx.Client(auth=(public_key, secret_key), timeout=20.0) as client:
            prompt_names = list_prompt_names(
                client=client,
                base_url=base_url,
                limit=max(1, args.limit),
                max_pages=max(1, args.max_pages),
                name_prefix=args.name_prefix,
            )
    except httpx.HTTPError as exc:
        print(f"Failed to list prompts: {exc}", file=sys.stderr)
        return 2

    if not prompt_names:
        print("No prompts found for the selected scope.")
        return 0

    print(f"Found {len(prompt_names)} prompt(s).")
    for name in prompt_names:
        print(f" - {name}")

    if args.dry_run:
        print("Dry-run only. No prompts deleted.")
        return 0

    if not args.yes:
        print(
            "WARNING: This will delete all listed prompts and all their versions.",
            file=sys.stderr,
        )
        confirm = input("Type YES/yes/y to continue: ").strip().lower()
        if confirm not in {"yes", "y"}:
            print("Aborted.")
            return 1

    ok = 0
    failed = 0
    with httpx.Client(auth=(public_key, secret_key), timeout=20.0) as client:
        for prompt_name in prompt_names:
            success, info = delete_prompt_all_versions(
                client=client,
                base_url=base_url,
                prompt_name=prompt_name,
            )
            if success:
                ok += 1
                print(f"[OK] {prompt_name} ({info})")
            else:
                failed += 1
                print(f"[FAIL] {prompt_name} ({info})", file=sys.stderr)

    print(f"Finished. deleted={ok} failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
