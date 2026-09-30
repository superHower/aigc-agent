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

    def get_file(self, file_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM files WHERE id = ?", (file_id,)
            ).fetchone()

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

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def get_job_by_output_name(self, output_name: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM jobs WHERE output_path LIKE ? ORDER BY updated_at DESC LIMIT 1",
                (f"%/{output_name}",),
            ).fetchone()

    def get_job_by_output_name(self, output_name: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM jobs WHERE output_path LIKE ? ORDER BY updated_at DESC LIMIT 1",
                (f"%/{output_name}",),
            ).fetchone()

    def get_jobs(self, task_id: str) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM jobs WHERE task_id = ? ORDER BY created_at", (task_id,)
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

    def set_task_status(self, task_id: str, status: str, error: str | None = None) -> None:
        with self._connect() as connection:
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
                "UPDATE jobs SET status = 'failed', error = 'process_restarted', updated_at = ? WHERE status = 'processing'",
                (utc_now(),),
            )
            connection.execute(
                "UPDATE tasks SET status = 'queued', updated_at = ? WHERE status IN ('running', 'cancelling')",
                (utc_now(),),
            )
