from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from backend.db.task_store import TaskStore
from backend.services.image_editor import ImageEditor
from backend.services.mask_generator import create_mask

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self, store: TaskStore, editor: ImageEditor, data_dir: Path, request_timeout: float, job_timeout: float, max_retries: int) -> None:
        self.store = store
        self.editor = editor
        self.data_dir = data_dir
        self.request_timeout = request_timeout
        self.job_timeout = job_timeout
        self.max_retries = max_retries
        self.running_tasks: dict[str, asyncio.Task[None]] = {}

    async def create_single_job(
        self,
        *,
        source_id: str,
        source_path: Path,
        width: int,
        height: int,
        bbox: tuple[int, int, int, int],
        prompt: str,
        size: str,
        quality: str,
        output_format: str,
    ) -> str:
        task_id = f"task_{uuid4().hex}"
        job_id = f"{task_id}_{source_id}_edit_none"
        mask_path = self.data_dir / "masks" / f"{job_id}.png"
        create_mask(width, height, bbox, mask_path)
        self.store.create_task(
            task_id,
            source_id,
            {
                "size": size,
                "quality": quality,
                "output_format": output_format,
                "strategy": "serial",
            },
            {
                "id": job_id,
                "step": "edit",
                "prompt": prompt,
                "mask_path": str(mask_path),
                "input_path": str(source_path),
            },
        )
        worker = asyncio.create_task(
            self._run_single_job(
                task_id, job_id, source_path, mask_path, prompt, size, quality, output_format
            )
        )
        self.running_tasks[task_id] = worker
        worker.add_done_callback(lambda _: self.running_tasks.pop(task_id, None))
        return task_id

    async def _run_single_job(
        self,
        task_id: str,
        job_id: str,
        input_path: Path,
        mask_path: Path,
        prompt: str,
        size: str,
        quality: str,
        output_format: str,
    ) -> None:
        self.store.set_task_status(task_id, "running")
        for attempt in range(self.max_retries + 1):
            job = self.store.get_job(job_id)
            if job is None:
                return
            if job["cancel_requested"]:
                self.store.update_job(job_id, status="cancelled")
                self.store.set_task_status(task_id, "cancelled")
                return
            self.store.update_job(job_id, status="processing", retry_count=attempt)
            try:
                output_path, _ = await asyncio.wait_for(
                    self.editor.edit(
                        job_id=job_id,
                        input_path=input_path,
                        mask_path=mask_path,
                        prompt=prompt,
                        size=size,
                        quality=quality,
                        output_format=output_format,
                        request_timeout=self.request_timeout,
                    ),
                    timeout=self.job_timeout,
                )
                job = self.store.get_job(job_id)
                if job and job["cancel_requested"]:
                    self.store.update_job(job_id, status="cancelled", error="cancelled_after_response")
                    self.store.set_task_status(task_id, "cancelled")
                    return
                self.store.update_job(job_id, status="done", output_path=str(output_path), error=None)
                self.store.set_task_status(task_id, "completed")
                return
            except asyncio.TimeoutError:
                self.store.update_job(job_id, status="failed", error="job_timeout", retry_count=attempt)
                self.store.set_task_status(task_id, "failed", "job_timeout")
                return
            except asyncio.CancelledError:
                self.store.update_job(job_id, status="cancelled", error="cancelled")
                self.store.set_task_status(task_id, "cancelled")
                return
            except Exception as exc:
                logger.exception("Job %s failed on attempt %s", job_id, attempt + 1)
                if attempt >= self.max_retries:
                    self.store.update_job(job_id, status="failed", error=str(exc), retry_count=attempt)
                    self.store.set_task_status(task_id, "failed", str(exc))
                    return
                await asyncio.sleep(min(2**attempt, 8))

    def cancel(self, task_id: str) -> tuple[int, int]:
        return self.store.request_cancel(task_id)
