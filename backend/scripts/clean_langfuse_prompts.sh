#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

uv run python "$ROOT_DIR/scripts/clean_langfuse_prompts.py" \
  --repo-root "$ROOT_DIR" \
  "$@"
