from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY,
                    original_name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analyses (
                    file_id TEXT PRIMARY KEY,
                    result TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (file_id) REFERENCES files(id)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_ids TEXT NOT NULL,
                    edit_rule TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    step TEXT NOT NULL,
                    target_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    prompt TEXT NOT NULL DEFAULT '',
                    mask_path TEXT,
                    input_path TEXT NOT NULL DEFAULT '',
                    output_path TEXT NOT NULL DEFAULT '',
                    error TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_task_id ON jobs(task_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_cancel ON jobs(cancel_requested)
                    WHERE cancel_requested = 1;
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
            if "sequence" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0")
            connection.execute("PRAGMA journal_mode = WAL")

    def register_file(self, record: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO files (id, original_name, path, mime_type, width, height, size, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["original_name"],
                    record["path"],
                    record["mime_type"],
                    record["width"],
                    record["height"],
                    record["size"],
                    record["created_at"],
                ),
            )

    def get_analysis(self, file_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT result FROM analyses WHERE file_id = ?", (file_id,)).fetchone()
            return row["result"] if row else None

    def save_analysis(self, file_id: str, result: str, files: list[dict[str, Any]]) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for record in files:
                connection.execute(
                    "INSERT INTO files (id, original_name, path, mime_type, width, height, size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(record[key] for key in ("id", "original_name", "path", "mime_type", "width", "height", "size", "created_at")),
                )
            connection.execute("INSERT INTO analyses (file_id, result, created_at) VALUES (?, ?, ?)", (file_id, result, utc_now()))

    def get_file(self, file_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM files WHERE id = ?", (file_id,)
            ).fetchone()

    def get_files(self, file_ids: list[str]) -> dict[str, sqlite3.Row]:
        if not file_ids:
            return {}
        placeholders = ",".join("?" for _ in file_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM files WHERE id IN ({placeholders})", file_ids
            ).fetchall()
        return {row["id"]: row for row in rows}

    def create_task(self, task_id: str, source_id: str, rule: dict[str, Any], job: dict[str, Any]) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO tasks (id, created_at, updated_at, source_ids, edit_rule) VALUES (?, ?, ?, ?, ?)",
                    (task_id, now, now, json.dumps([source_id]), json.dumps(rule)),
                )
                connection.execute(
                    """
                    INSERT INTO jobs
                    (id, task_id, source_id, step, prompt, mask_path, input_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job["id"], task_id, source_id, job["step"], job["prompt"],
                        job["mask_path"], job["input_path"], now, now,
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def get_task(self, task_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    def list_tasks(self, limit: int = 50, offset: int = 0) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def get_job_by_output_name(self, output_name: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            for row in connection.execute("SELECT * FROM jobs WHERE status = 'done' AND output_path != ''"):
                if Path(row["output_path"]).name == output_name:
                    return row
            return None

    def get_done_output_paths(self, output_names: list[str]) -> dict[str, Path]:
        if not output_names:
            return {}
        result: dict[str, Path] = {}
        with self._connect() as connection:
            rows = connection.execute("SELECT output_path FROM jobs WHERE status = 'done' AND output_path != ''").fetchall()
        wanted = set(output_names)
        for row in rows:
            path = Path(row["output_path"])
            if path.name in wanted:
                result[path.name] = path
        return result

    def get_jobs(self, task_id: str) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM jobs WHERE task_id = ? ORDER BY sequence, rowid", (task_id,)
            ).fetchall()

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {
            "status", "input_path", "output_path", "error", "retry_count",
            "cancel_requested", "prompt", "mask_path",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    f"UPDATE jobs SET {assignments} WHERE id = ?",
                    (*updates.values(), job_id),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def reset_task_for_retry(self, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = 'queued', error = NULL, updated_at = ? WHERE id = ?",
                (utc_now(), task_id),
            )

    def set_task_status(self, task_id: str, status: str, error: str | None = None) -> None:
        with self._connect() as connection:
            current = connection.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if current and current["status"] in {"completed", "partial_failed", "failed", "cancelled"}:
                if current["status"] != status:
                    raise ValueError("task terminal state cannot be changed")
                return
            connection.execute(
                "UPDATE tasks SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, utc_now(), task_id),
            )

    def request_cancel(self, task_id: str) -> tuple[int, int]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                pending = connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE task_id = ? AND status IN ('pending', 'processing')",
                    (task_id,),
                ).fetchone()[0]
                done = connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE task_id = ? AND status = 'done'",
                    (task_id,),
                ).fetchone()[0]
                connection.execute(
                    "UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE task_id = ? AND status IN ('pending', 'processing')",
                    (utc_now(), task_id),
                )
                connection.execute(
                    "UPDATE tasks SET status = 'cancelling', updated_at = ? WHERE id = ? AND status IN ('queued', 'running', 'cancelling')",
                    (utc_now(), task_id),
                )
                connection.execute("COMMIT")
                return pending, done
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def recover_processing(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = 'failed', error = 'process_restarted', updated_at = ? WHERE status = 'processing' AND cancel_requested = 0",
                (utc_now(),),
            )
            connection.execute(
                "UPDATE jobs SET status = 'cancelled', updated_at = ? WHERE cancel_requested = 1 AND status IN ('pending', 'processing', 'failed')",
                (utc_now(),),
            )
            connection.execute(
                "UPDATE tasks SET status = 'queued', updated_at = ? WHERE status IN ('running', 'cancelling')",
                (utc_now(),),
            )

    def list_active_tasks(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM tasks WHERE status IN ('queued', 'running', 'cancelling')").fetchall()

    def create_batch(self, task_id: str, source_ids: list[str], rule: dict[str, Any], jobs: list[dict[str, Any]]) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO tasks (id, created_at, updated_at, source_ids, edit_rule) VALUES (?, ?, ?, ?, ?)",
                (task_id, now, now, json.dumps(source_ids), json.dumps(rule)),
            )
            for sequence, job in enumerate(jobs):
                connection.execute(
                    """INSERT INTO jobs (id, task_id, source_id, step, target_id, status, prompt, mask_path,
                    input_path, output_path, sequence, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (job["id"], task_id, job["source_id"], job["step"], job.get("target_id"),
                     job.get("status", "pending"), job["prompt"], job["mask_path"], job["input_path"],
                     job.get("output_path", ""), sequence, now, now),
                )

    def get_pending_jobs(self, task_id: str) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM jobs WHERE task_id = ? AND status IN ('pending', 'failed') ORDER BY sequence, rowid",
                (task_id,),
            ).fetchall()

    def finalize_task(self, task_id: str) -> str:
        with self._connect() as connection:
            jobs = connection.execute("SELECT status FROM jobs WHERE task_id = ?", (task_id,)).fetchall()
            task = connection.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise ValueError("task not found")
            statuses = [job["status"] for job in jobs]
            if any(status in {"pending", "processing"} for status in statuses):
                return task["status"]
            if task["status"] == "cancelling" and any(status == "cancelled" for status in statuses):
                final = "cancelled"
            elif statuses and all(status == "done" for status in statuses):
                final = "completed"
            elif any(status == "done" for status in statuses):
                final = "partial_failed"
            elif any(status == "cancelled" for status in statuses):
                final = "cancelled"
            else:
                final = "failed"
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ? AND status NOT IN ('completed', 'partial_failed', 'failed', 'cancelled')",
                (final, utc_now(), task_id),
            )
            return final
