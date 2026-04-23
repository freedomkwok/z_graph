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
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = REPO_ROOT / "database"
BACKEND_DIR = REPO_ROOT / "backend"
ENV_FILE = DATABASE_DIR / ".env"
FALLBACK_ENV_FILE = DATABASE_DIR / ".env.example"
LEGACY_ENV_FILE = BACKEND_DIR / ".env"
LEGACY_FALLBACK_ENV_FILE = BACKEND_DIR / ".env.example"


def _load_env() -> None:
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    elif FALLBACK_ENV_FILE.exists():
        load_dotenv(FALLBACK_ENV_FILE)
    elif LEGACY_ENV_FILE.exists():
        load_dotenv(LEGACY_ENV_FILE)
    else:
        load_dotenv(LEGACY_FALLBACK_ENV_FILE)


def _get_connection_string() -> str:
    direct = str(os.getenv("PROJECT_STORAGE_CONNECTION_STRING") or "").strip()
    if direct:
        return direct
    user = os.getenv("POSTGRES_USER", "z_graph")
    password = os.getenv("POSTGRES_PASSWORD", "zep_graph_password")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "z_graph")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _fetch_latest_task(cur: psycopg.Cursor[Any], task_id: str | None) -> dict[str, Any] | None:
    if task_id:
        cur.execute(
            """
            SELECT
                task_id,
                project_id,
                status,
                batch_size,
                total_chunks,
                total_batches,
                created_at
            FROM graph_build
            WHERE task_id = %s
            LIMIT 1
            """,
            (task_id,),
        )
    else:
        cur.execute(
            """
            SELECT
                task_id,
                project_id,
                status,
                batch_size,
                total_chunks,
                total_batches,
                created_at
            FROM graph_build
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "task_id": str(row[0]),
        "project_id": str(row[1] or "") or None,
        "status": str(row[2] or ""),
        "batch_size": int(row[3]) if row[3] is not None else None,
        "total_chunks": int(row[4]) if row[4] is not None else None,
        "total_batches": int(row[5]) if row[5] is not None else None,
        "created_at": str(row[6] or ""),
    }


def _build_status_patch(
    *,
    mode: str,
    processed_chunks: int,
    batch_size: int,
    existing_total_chunks: int | None,
) -> dict[str, Any]:
    total_chunks = max(int(existing_total_chunks or 0), int(processed_chunks))
    total_batches = max(1, int(math.ceil(total_chunks / max(1, batch_size))))
    completed_batch_count = max(0, int(math.ceil(processed_chunks / max(1, batch_size))))
    last_completed_batch_index = min(total_batches - 1, max(-1, completed_batch_count - 1))

    if mode == "pickup":
        status = "failed"
        resume_state = "resuming"
        progress = min(99, max(1, int((completed_batch_count / total_batches) * 100)))
        message = (
            f"[fake_insert] forced resumable checkpoint at chunk={processed_chunks}, "
            f"batch_index={last_completed_batch_index}"
        )
    else:
        status = "completed"
        resume_state = "completed"
        progress = 100
        message = f"[fake_insert] forced success after chunk={processed_chunks}"

    return {
        "status": status,
        "resume_state": resume_state,
        "progress": progress,
        "message": message,
        "total_chunks": total_chunks,
        "total_batches": total_batches,
        "last_completed_batch_index": last_completed_batch_index,
    }


def _merge_project_data_for_fake(
    *,
    existing: dict[str, Any],
    mode: str,
    task_id: str,
) -> dict[str, Any]:
    """Align projects.project_data JSON with graph_build fake state (same fields as Project.to_dict)."""
    merged = dict(existing)
    if mode == "success":
        merged["status"] = "graph_completed"
        merged["graph_build_task_id"] = None
        merged["has_built_graph"] = True
        merged["error"] = None
    else:
        merged["status"] = "graph_building"
        merged["graph_build_task_id"] = task_id
    merged["updated_at"] = datetime.now().isoformat()
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fake-update latest graph_build row. "
            "mode=success marks completed; mode=pickup marks failed/resumable to force resume pickup."
        )
    )
    parser.add_argument("--task-id", default="", help="Target a specific task_id instead of latest row.")
    parser.add_argument(
        "--mode",
        choices=["success", "pickup"],
        default="success",
        help="success=mark completed, pickup=mark failed/resumable for resume matching.",
    )
    parser.add_argument(
        "--processed-chunks",
        type=int,
        default=200,
        help="How many chunks you want this fake row to represent as processed.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Fallback batch size if row has no batch_size yet.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print target + patch, do not UPDATE.")
    parser.add_argument(
        "--skip-project-json",
        action="store_true",
        help="Do not update projects.project_data (only update graph_build, and has_built_graph for success).",
    )
    args = parser.parse_args()

    _load_env()
    connection_string = _get_connection_string()
    now_iso = datetime.now().isoformat()
    normalized_task_id = str(args.task_id or "").strip() or None

    with psycopg.connect(connection_string) as conn:
        with conn.cursor() as cur:
            target = _fetch_latest_task(cur, normalized_task_id)
            if not target:
                raise RuntimeError("No graph_build row found.")

            effective_batch_size = int(target["batch_size"] or args.batch_size)
            patch = _build_status_patch(
                mode=args.mode,
                processed_chunks=max(0, int(args.processed_chunks)),
                batch_size=max(1, effective_batch_size),
                existing_total_chunks=target["total_chunks"],
            )

            print(f"target_task_id={target['task_id']}")
            print(f"target_created_at={target['created_at']}")
            print(f"previous_status={target['status']}")
            print(f"mode={args.mode}")
            print(f"patch={patch}")

            if args.dry_run:
                return

            cur.execute(
                """
                UPDATE graph_build
                SET
                    status = %s,
                    progress = %s,
                    message = %s,
                    error = NULL,
                    resume_state = %s,
                    total_chunks = %s,
                    total_batches = %s,
                    last_completed_batch_index = %s,
                    updated_at = %s
                WHERE task_id = %s
                """,
                (
                    patch["status"],
                    patch["progress"],
                    patch["message"],
                    patch["resume_state"],
                    patch["total_chunks"],
                    patch["total_batches"],
                    patch["last_completed_batch_index"],
                    now_iso,
                    target["task_id"],
                ),
            )

            if target["project_id"] and not args.skip_project_json:
                cur.execute(
                    "SELECT project_data FROM projects WHERE project_id = %s LIMIT 1",
                    (target["project_id"],),
                )
                prow = cur.fetchone()
                if prow is None:
                    print(
                        f"Warning: no projects row for project_id={target['project_id']}, "
                        "skipping project_data update.",
                    )
                else:
                    raw_pd = prow[0]
                    if isinstance(raw_pd, dict):
                        existing_pd: dict[str, Any] = raw_pd
                    elif raw_pd is None:
                        existing_pd = {}
                    else:
                        existing_pd = json.loads(raw_pd) if isinstance(raw_pd, str) else {}

                    new_pd = _merge_project_data_for_fake(
                        existing=existing_pd,
                        mode="success" if patch["status"] == "completed" else "pickup",
                        task_id=target["task_id"],
                    )
                    cur.execute(
                        """
                        UPDATE projects
                        SET
                            project_data = %s::jsonb,
                            updated_at = %s,
                            has_built_graph = CASE
                                WHEN %s THEN TRUE
                                ELSE has_built_graph
                            END
                        WHERE project_id = %s
                        """,
                        (
                            json.dumps(new_pd, ensure_ascii=False),
                            now_iso,
                            patch["status"] == "completed",
                            target["project_id"],
                        ),
                    )
                    print(
                        f"Updated projects.project_data for project_id={target['project_id']} "
                        f"(status={new_pd.get('status')}, graph_build_task_id={new_pd.get('graph_build_task_id')!r})",
                    )
            elif args.skip_project_json and patch["status"] == "completed" and target["project_id"]:
                cur.execute(
                    """
                    UPDATE projects
                    SET
                        has_built_graph = TRUE,
                        updated_at = %s
                    WHERE project_id = %s
                    """,
                    (now_iso, target["project_id"]),
                )

        conn.commit()

    print("Done.")
    print(
        "Tip: use --mode pickup if you want resume lookup to pick this row "
        "(resume query matches pending/processing/failed)."
    )


if __name__ == "__main__":
    main()
