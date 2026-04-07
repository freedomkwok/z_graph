#!/usr/bin/env bash
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: this script must be run inside a git repository."
  exit 1
fi

branch_name="$(git rev-parse --abbrev-ref HEAD)"
if [[ "${branch_name}" == "HEAD" ]]; then
  echo "Error: detached HEAD is not supported. Checkout a branch first."
  exit 1
fi

commit_message="${*:-}"
if [[ -z "${commit_message}" ]]; then
  commit_message="Auto commit $(date '+%Y-%m-%d %H:%M:%S %Z')"
fi

echo "Staging all changes..."
git add -A

if git diff --cached --quiet; then
  echo "No staged changes to commit."
  exit 0
fi

echo "Creating commit on ${branch_name}..."
git commit -m "${commit_message}"

if git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1; then
  echo "Pushing to tracked upstream..."
  git push
else
  echo "No upstream set. Pushing with upstream to origin/${branch_name}..."
  git push -u origin "${branch_name}"
fi

echo "Done."
