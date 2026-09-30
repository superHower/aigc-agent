from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4

from backend.db.task_store import TaskStore
from backend.services.image_editor import ImageEditor
from backend.services.mask_generator import create_mask
from PIL import Image

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self, store: TaskStore, editor: ImageEditor, data_dir: Path, request_timeout: float, job_timeout: float, max_retries: int, max_concurrency: int = 3) -> None:
        self.store = store
        self.editor = editor
        self.data_dir = data_dir
        self.request_timeout = request_timeout
        self.job_timeout = job_timeout
        self.max_retries = max_retries
        self.api_semaphore = asyncio.Semaphore(max_concurrency)
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
        reference_path: Path | None = None,
        mask_path: Path | None = None,
    ) -> str:
        task_id = f"task_{uuid4().hex}"
        job_id = f"{task_id}_{source_id}_edit_none"
        mask_path = mask_path or self.data_dir / "masks" / f"{job_id}.png"
        if not mask_path.exists():
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
                task_id, job_id, source_path, mask_path, prompt, size, quality, output_format, reference_path
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
        reference_path: Path | None = None,
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
                async with self.api_semaphore:
                    output_path, _ = await asyncio.wait_for(
                        self.editor.edit(
                        job_id=job_id,
                        input_path=input_path,
                        mask_path=mask_path,
                        prompt=prompt,
                        size=size,
                        quality=quality,
                        output_format=output_format,
                        reference_path=reference_path,
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
                self.store.finalize_task(task_id)
                return
            except asyncio.TimeoutError:
                self.store.update_job(job_id, status="failed", error="job_timeout", retry_count=attempt)
                self.store.finalize_task(task_id)
                return
            except asyncio.CancelledError:
                self.store.update_job(job_id, status="cancelled", error="cancelled")
                self.store.finalize_task(task_id)
                return
            except Exception as exc:
                logger.exception("Job %s failed on attempt %s", job_id, attempt + 1)
                if attempt >= self.max_retries:
                    self.store.update_job(job_id, status="failed", error=str(exc), retry_count=attempt)
                    self.store.finalize_task(task_id)
                    return
                await asyncio.sleep(min(2**attempt, 8))

    def cancel(self, task_id: str) -> tuple[int, int]:
        return self.store.request_cancel(task_id)

    async def retry(self, task_id: str, job_id: str | None = None) -> None:
        task = self.store.get_task(task_id)
        if task is None:
            raise ValueError("task not found")
        jobs = self.store.get_jobs(task_id)
        selected = [job for job in jobs if job_id is None or job["id"] == job_id]
        if not selected:
            raise ValueError("job not found")
        if any(job["status"] in {"pending", "processing"} for job in selected):
            raise ValueError("job is already running")
        for job in selected:
            self.store.update_job(job["id"], status="pending", error=None, cancel_requested=0)
        rule = json.loads(task["edit_rule"])
        source_jobs: dict[str, list[dict[str, str]]] = {}
        for job in jobs:
            if job["status"] == "done" and job["id"] not in {item["id"] for item in selected}:
                continue
            source_jobs.setdefault(job["source_id"], []).append(dict(job))
        self.store.reset_task_for_retry(task_id)
        worker = asyncio.create_task(self._run_batch(task_id, source_jobs, rule))
        self.running_tasks[task_id] = worker
        worker.add_done_callback(lambda _: self.running_tasks.pop(task_id, None))

    async def create_batch(self, task_id: str, source_jobs: dict[str, list[dict[str, str]]], rule: dict) -> None:
        worker = asyncio.create_task(self._run_batch(task_id, source_jobs, rule))
        self.running_tasks[task_id] = worker
        worker.add_done_callback(lambda _: self.running_tasks.pop(task_id, None))

    async def _run_batch(self, task_id: str, source_jobs: dict[str, list[dict[str, str]]], rule: dict) -> None:
        self.store.set_task_status(task_id, "running")
        await asyncio.gather(*(self._run_source_chain(task_id, source_id, jobs, rule) for source_id, jobs in source_jobs.items()))
        self.store.finalize_task(task_id)

    async def _run_source_chain(self, task_id: str, source_id: str, jobs: list[dict[str, str]], rule: dict) -> None:
        current_input = Path(jobs[0]["input_path"]) if jobs else None
        for job_data in jobs:
            if current_input is not None:
                job_data["input_path"] = str(current_input)
            job = self.store.get_job(job_data["id"])
            if job is None or job["status"] == "done":
                if job and job["output_path"]:
                    current_input = Path(job["output_path"])
                continue
            await self._run_job_with_retries(task_id, job_data, rule)
            completed = self.store.get_job(job_data["id"])
            if completed is None or completed["status"] != "done":
                return
            current_input = Path(completed["output_path"])

    def _scaled_mask(self, mask_path: Path, input_path: Path, job_id: str) -> Path:
        with Image.open(mask_path) as mask, Image.open(input_path) as image:
            if mask.size == image.size:
                return mask_path
            scaled = self.data_dir / "masks" / f"{job_id}_{image.width}x{image.height}.png"
            scaled.parent.mkdir(parents=True, exist_ok=True)
            mask.resize(image.size, Image.Resampling.NEAREST).save(scaled, "PNG", optimize=True)
            return scaled

    async def _run_job_with_retries(self, task_id: str, job_data: dict[str, str], rule: dict) -> None:
        for attempt in range(self.max_retries + 1):
            job = self.store.get_job(job_data["id"])
            if job is None:
                return
            if job["cancel_requested"]:
                self.store.update_job(job_data["id"], status="cancelled")
                return
            self.store.update_job(job_data["id"], status="processing", retry_count=attempt, input_path=job_data["input_path"])
            try:
                input_path = Path(job_data["input_path"])
                mask_path = self._scaled_mask(Path(job_data["mask_path"]), input_path, job_data["id"])
                async with self.api_semaphore:
                    output_path, _ = await asyncio.wait_for(self.editor.edit(
                        job_id=job_data["id"], input_path=input_path, mask_path=mask_path,
                        prompt=job_data["prompt"], size=rule["size"], quality=rule["quality"],
                        output_format=rule["output_format"], request_timeout=self.request_timeout,
                        reference_path=Path(job_data["reference_path"]) if job_data.get("reference_path") else None,
                    ), timeout=self.job_timeout)
                job = self.store.get_job(job_data["id"])
                if job and job["cancel_requested"]:
                    self.store.update_job(job_data["id"], status="cancelled", error="cancelled_after_response")
                    return
                self.store.update_job(job_data["id"], status="done", output_path=str(output_path), error=None)
                return
            except asyncio.TimeoutError:
                self.store.update_job(job_data["id"], status="failed", error="job_timeout", retry_count=attempt)
                return
            except asyncio.CancelledError:
                self.store.update_job(job_data["id"], status="cancelled", error="cancelled")
                return
            except Exception as exc:
                if attempt >= self.max_retries:
                    self.store.update_job(job_data["id"], status="failed", error=str(exc), retry_count=attempt)
                    return
                await asyncio.sleep(min(2 ** attempt, 8))
