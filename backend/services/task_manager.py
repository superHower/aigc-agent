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
from backend.services.multi_image import fit_output
from backend.services.channels import ChannelPool, ChannelUnavailable
from backend.services import credits
from backend.services import attempts
from backend.services.admission import Admission
from backend.db.task_store import utc_now

logger = logging.getLogger(__name__)


async def _join_jobs(coroutines) -> None:
    # Drain sibling work before a caller finalizes the task and releases credits.
    results = await asyncio.gather(*coroutines, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result


class TaskManager:
    def __init__(self, store: TaskStore, editor: ImageEditor, data_dir: Path, request_timeout: float, job_timeout: float, max_retries: int, max_concurrency: int = 3, channel_pool: ChannelPool | None = None, ordinary_concurrency: int = 1, member_concurrency: int = 3) -> None:
        self.store = store
        self.editor = editor
        self.data_dir = data_dir
        self.request_timeout = request_timeout
        self.job_timeout = job_timeout
        self.max_retries = max_retries
        self.api_semaphore = asyncio.Semaphore(max_concurrency)
        self.running_tasks: dict[str, asyncio.Task[None]] = {}
        self.channel_pool = channel_pool
        self.assignments: dict[str, dict] = {}
        self.admission = Admission(store, ordinary_concurrency, member_concurrency)
        from backend.services.video import VideoRunner
        self.video_runner = VideoRunner(self)

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
            attempt_id = None
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
                    attempt_id = attempts.start(self.store, job_id, editor=self.editor, retry_round=attempt)
                    dispatch_options = {'on_dispatch': lambda: attempts.dispatched(self.store, attempt_id)} if isinstance(self.editor, ImageEditor) else {}
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
                        **dispatch_options,
                        ),
                        timeout=self.job_timeout,
                    )
                job = self.store.get_job(job_id)
                attempts.finish(self.store, attempt_id, 'done')
                if job and job["cancel_requested"]:
                    with self.store.transaction() as db:
                        db.execute('UPDATE generation_attempts SET response_after_cancel=1 WHERE id=?', (attempt_id,))
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
                logger.error("Job %s failed on attempt %s (%s)", job_id, attempt + 1, type(exc).__name__)
                if attempt >= self.max_retries:
                    self.store.update_job(job_id, status="failed", error=str(exc), retry_count=attempt)
                    self.store.finalize_task(task_id)
                    return
                await asyncio.sleep(min(2**attempt, 8))
            finally:
                if attempt_id:
                    attempts.finish(self.store, attempt_id, 'unknown', 'execution_interrupted_or_failed')

    def cancel(self, task_id: str) -> tuple[int, int]:
        return self.store.request_cancel(task_id)

    async def retry(self, task_id: str, job_id: str | None = None) -> None:
        task = self.store.get_task(task_id)
        if task is None:
            raise ValueError("task not found")
        if task_id in self.running_tasks:
            raise ValueError("task is already running")
        jobs = self.store.get_jobs(task_id)
        selected = [job for job in jobs if job["status"] in {"failed", "cancelled"} and (job_id is None or job["id"] == job_id)]
        if not selected:
            raise ValueError("job not found")
        if any(job["status"] in {"pending", "processing"} for job in selected):
            raise ValueError("job is already running")
        for job in selected:
            self.store.update_job(job["id"], status="pending", error=None, cancel_requested=0)
        rule = json.loads(task["edit_rule"])
        rule['execution_job_ids'] = [job['id'] for job in selected]
        with self.store.transaction() as db:
            db.execute('UPDATE tasks SET edit_rule=? WHERE id=?', (json.dumps(rule), task_id))
        source_jobs: dict[str, list[dict[str, str]]] = {}
        for job in jobs:
            source_jobs.setdefault(job["source_id"], []).append(dict(job))
        self.store.reset_task_for_retry(task_id)
        worker = asyncio.create_task(self._run_batch(task_id, source_jobs, rule))
        self.running_tasks[task_id] = worker
        worker.add_done_callback(lambda _: self.running_tasks.pop(task_id, None))

    async def create_batch(self, task_id: str, source_jobs: dict[str, list[dict[str, str]]], rule: dict) -> None:
        worker = asyncio.create_task(self._run_batch(task_id, source_jobs, rule))
        self.running_tasks[task_id] = worker
        worker.add_done_callback(lambda _: self.running_tasks.pop(task_id, None))

    async def resume_active_tasks(self) -> None:
        """Resume queued tasks after a process restart.

        Jobs that were in-flight are marked failed by the store recovery step.
        Passing every job back to the source chain is intentional: completed
        jobs are skipped while their output is used as the next chain input.
        """
        # A durable completion receipt bridges filesystem output and DB commit.
        receipt_dir = self.data_dir / 'receipts'
        for receipt in receipt_dir.glob('*.json'):
            try:
                data = json.loads(receipt.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                logger.warning('Ignoring unreadable completion receipt %s', receipt.name)
                continue
            job = self.store.get_job(data['job_id'])
            if job and job['status'] != 'done' and not job['cancel_requested'] and data.get('execution_token') == credits.execution_token(self.store, job['id']) and Path(data['output_path']).is_file():
                self.store.update_job(job['id'], status='done', output_path=data['output_path'], error=None)
        with self.store.transaction() as db:
            credits.begin(db)
            db.execute("UPDATE generation_attempts SET status='unknown',ended_at=? WHERE ended_at IS NULL", (utc_now(),))
            for row in db.execute('SELECT id,status FROM tasks').fetchall():
                credits.reconcile_task(db, row['id'], row['status'] in ('completed', 'partial_failed', 'failed', 'cancelled'))
        for task in self.store.list_active_tasks():
            if task["id"] in self.running_tasks:
                continue
            jobs = self.store.get_jobs(task["id"])
            if not jobs:
                self.store.finalize_task(task["id"])
                continue
            rule = json.loads(task["edit_rule"])
            source_jobs: dict[str, list[dict[str, str]]] = {}
            for job in jobs:
                source_jobs.setdefault(job["source_id"], []).append(dict(job))
            await self.create_batch(task["id"], source_jobs, rule)

    async def _run_batch(self, task_id: str, source_jobs: dict[str, list[dict[str, str]]], rule: dict) -> None:
        scope = rule.get('execution_job_ids')
        if scope:
            source_jobs = {source: [job for job in jobs if job['id'] in scope or job['status'] == 'done'] for source, jobs in source_jobs.items()}
            source_jobs = {source: jobs for source, jobs in source_jobs.items() if jobs}
        self.store.set_task_status(task_id, "running")
        try:
            if rule.get('generation_kind') == 'video':
                await self.video_runner.run(task_id, source_jobs, rule)
                self.store.finalize_task(task_id)
                return
            while True:
                await self._run_batch_round(task_id, source_jobs, rule)
                if not self.channel_pool or not self.channel_pool.store.available(task_id):
                    break
                with self.store.transaction() as db:
                    risk = db.execute("SELECT value FROM system_settings WHERE key='risk_retry_limit'").fetchone()
                current_task = self.store.get_task(task_id)
                if risk and int(risk['value']) > 0 and current_task['auto_retry_count'] >= int(risk['value']):
                    break
                if not self.store.prepare_auto_retry(task_id, scope):
                    break
                # Rebuild complete chains: successful prerequisites supply their outputs,
                # while only failed steps are queued again.
                source_jobs = {}
                for job in self.store.get_jobs(task_id):
                    if scope and job['id'] not in scope and job['status'] != 'done':
                        continue
                    source_jobs.setdefault(job["source_id"], []).append(dict(job))
            self.store.finalize_task(task_id)
        except Exception:
            logger.error('Task %s stopped unexpectedly', task_id)
            for job in self.store.get_jobs(task_id):
                if job['status'] in ('pending', 'processing'):
                    self.store.update_job(job['id'], status='failed', error='execution_interrupted')
            self.store.finalize_task(task_id)
            raise
        finally:
            self.assignments.pop(task_id, None)
            if self.channel_pool:
                self.channel_pool.release_task(task_id)

    async def _run_batch_round(self, task_id: str, source_jobs: dict[str, list[dict[str, str]]], rule: dict) -> None:
        if self.channel_pool:
            channels = self.channel_pool.snapshot(task_id)
            all_jobs = [job for jobs in source_jobs.values() for job in jobs
                        if (stored := self.store.get_job(job["id"])) and stored["status"] == "pending"]
            if not channels:
                for job in all_jobs:
                    stored = self.store.get_job(job["id"])
                    if stored and stored["status"] == "pending":
                        self.store.update_job(job["id"], status="cancelled" if stored["cancel_requested"] else "failed", error="当前任务没有可用渠道，部分渠道可能因网络异常已在此任务中排除")
                return
            # Give final outputs their own round-robin so OCR prerequisites do not skew allocation.
            variants = [job for job in all_jobs if job["step"].startswith("custom_")]
            prerequisites = [job for job in all_jobs if not job["step"].startswith("custom_")]
            assigned = {}
            for group in (variants, prerequisites):
                for index, job in enumerate(group):
                    assigned[job["id"]] = channels[index % len(channels)]
                    self.store.update_job(job["id"], channel_name=channels[index % len(channels)].config["name"])
            self.assignments[task_id] = assigned
        try:
            await _join_jobs(self._run_source_chain(task_id, source_id, jobs, rule) for source_id, jobs in source_jobs.items())
        finally:
            self.assignments.pop(task_id, None)

    async def _run_source_chain(self, task_id: str, source_id: str, jobs: list[dict[str, str]], rule: dict) -> None:
        current_input = Path(jobs[0]["input_path"]) if jobs else None
        if rule.get("multi_image"):
            variants = []
            for job_data in jobs:
                if rule.get("outputs", {}).get(job_data["id"], {}).get("variant"):
                    variants.append(job_data)
                    continue
                job = self.store.get_job(job_data["id"])
                if job and job["status"] == "done":
                    current_input = Path(job["output_path"])
                    continue
                job_data["input_path"] = str(current_input)
                await self._run_job_with_retries(task_id, job_data, rule)
                completed = self.store.get_job(job_data["id"])
                if completed is None or completed["status"] != "done":
                    for remaining in jobs:
                        stored = self.store.get_job(remaining["id"])
                        if stored and stored["status"] == "pending":
                            self.store.update_job(remaining["id"], status="cancelled" if completed and completed["status"] == "cancelled" else "failed", error="文字编辑前置步骤未完成")
                    return
                current_input = Path(completed["output_path"])
            for variant in variants:
                if not rule.get('outputs', {}).get(variant['id'], {}).get('refinement'):
                    variant["input_path"] = str(current_input)
            await _join_jobs(self._run_job_with_retries(task_id, variant, rule) for variant in variants)
            return
        for job_data in jobs:
            if current_input is not None:
                job_data["input_path"] = str(current_input)
            is_variant = job_data["step"].startswith("custom_")
            job = self.store.get_job(job_data["id"])
            if job is None or job["status"] == "done":
                if job and job["output_path"]:
                    current_input = Path(job["output_path"])
                continue
            await self._run_job_with_retries(task_id, job_data, rule)
            completed = self.store.get_job(job_data["id"])
            if completed is None or completed["status"] != "done":
                for remaining in jobs:
                    stored = self.store.get_job(remaining["id"])
                    if stored and stored["status"] == "pending":
                        self.store.update_job(remaining["id"], status="cancelled" if stored["cancel_requested"] else "failed", error="前置步骤未完成")
                return
            if not is_variant:
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
        await self._execute_job(task_id, job_data, rule)

    async def _execute_job(self, task_id: str, job_data: dict[str, str], rule: dict) -> None:
        runtime = self.assignments.get(task_id, {}).get(job_data["id"])
        stored = self.store.get_job(job_data["id"])
        retry_offset = stored["retry_count"] if runtime and stored else 0
        for attempt in range(1 if runtime else self.max_retries + 1):
            attempt_id = None
            job = self.store.get_job(job_data["id"])
            if job is None or job["status"] == "done":
                return
            if self.channel_pool and task_id in self.assignments and runtime is None:
                return
            if job["status"] != "pending" and runtime:
                return
            if job["cancel_requested"]:
                self.store.update_job(job_data["id"], status="cancelled")
                return
            try:
                input_path = Path(job_data["input_path"])
                task = self.store.get_task(task_id)
                owner = task['owner_id'] if task and task['billable'] else None
                capacity = runtime.semaphore if runtime else self.api_semaphore
                async with self.admission.slot(owner, capacity, runtime):
                    job = self.store.get_job(job_data["id"])
                    if job and job["cancel_requested"]:
                        self.store.update_job(job_data["id"], status="cancelled")
                        return
                    def mark_processing():
                        nonlocal attempt_id
                        current = self.store.get_job(job_data["id"])
                        if current is None or current["cancel_requested"]:
                            return False
                        task = self.store.get_task(task_id)
                        if task and task['billable']:
                            with self.store.transaction() as db:
                                user = db.execute('SELECT disabled FROM users WHERE id=?', (task['owner_id'],)).fetchone()
                            if not user or user['disabled']:
                                self.store.update_job(job_data['id'], status='cancelled', cancel_requested=1, error='account_disabled')
                                return False
                        attempt_id = attempts.start(self.store, job_data['id'], runtime, runtime.editor if runtime else self.editor, retry_offset + attempt)
                        self.store.update_job(job_data["id"], status="processing", retry_count=retry_offset + attempt, input_path=str(input_path))
                        return True

                    if runtime is None:
                        if not mark_processing():
                            return
                    mask_path = self._scaled_mask(Path(job_data["mask_path"]), input_path, job_data["id"])
                    output_options = rule.get("outputs", {}).get(job_data["id"], {})
                    edit = self.editor.edit if runtime is None else lambda **kwargs: self.channel_pool.edit(runtime, on_start=mark_processing, capacity_reserved=True, **kwargs)
                    target_editor = runtime.editor if runtime else self.editor
                    def mark_dispatched():
                        if attempt_id:
                            attempts.dispatched(self.store, attempt_id)
                    dispatch_options = {'on_dispatch': mark_dispatched} if isinstance(target_editor, ImageEditor) else {}
                    output_path, _ = await asyncio.wait_for(edit(
                        job_id=job_data["id"], input_path=input_path, mask_path=mask_path,
                        prompt=job_data["prompt"], size=output_options.get("size", rule["size"]), quality=rule["quality"],
                        output_format=rule["output_format"], request_timeout=self.request_timeout,
                        reference_paths=[] if output_options.get('refinement') else [Path(path) for path in rule.get("reference_paths", [])],
                        **dispatch_options,
                    ), timeout=None if runtime else self.job_timeout)
                    if output_options.get("width"):
                        await asyncio.to_thread(fit_output, output_path, output_options["width"], output_options["height"])
                job = self.store.get_job(job_data["id"])
                if job and job["cancel_requested"]:
                    self.store.update_job(job_data["id"], status="cancelled", error="cancelled_after_response")
                    if attempt_id:
                        with self.store.transaction() as db:
                            db.execute("UPDATE generation_attempts SET ended_at=?,status='done',response_after_cancel=1 WHERE id=?", (utc_now(), attempt_id))
                    return
                receipt_dir = self.data_dir / 'receipts'
                receipt_dir.mkdir(parents=True, exist_ok=True)
                receipt = receipt_dir / f"{job_data['id']}.json"
                temporary = receipt.with_suffix('.tmp')
                temporary.write_text(json.dumps({'job_id': job_data['id'], 'output_path': str(output_path), 'execution_token': credits.execution_token(self.store, job_data['id'])}), encoding='utf-8')
                temporary.replace(receipt)
                self.store.update_job(job_data["id"], status="done", output_path=str(output_path), error=None)
                if attempt_id:
                    with self.store.transaction() as db:
                        db.execute("UPDATE generation_attempts SET ended_at=?,status='done' WHERE id=?", (utc_now(), attempt_id))
                return
            except ChannelUnavailable as exc:
                if attempt_id:
                    attempts.finish(self.store, attempt_id, 'failed', 'channel_unavailable')
                self.store.update_job(job_data["id"], status="failed", error=str(exc), retry_count=retry_offset + attempt)
                return
            except asyncio.TimeoutError:
                if attempt_id:
                    attempts.finish(self.store, attempt_id, 'unknown', 'timeout')
                self.store.update_job(job_data["id"], status="failed", error="job_timeout", retry_count=retry_offset + attempt)
                return
            except asyncio.CancelledError:
                if attempt_id:
                    attempts.finish(self.store, attempt_id, 'unknown', 'cancelled')
                self.store.update_job(job_data["id"], status="cancelled", error="cancelled")
                return
            except Exception as exc:
                if attempt_id:
                    attempts.finish(self.store, attempt_id, 'failed', 'generation_failed')
                logger.error("Job %s failed on attempt %s (%s)", job_data["id"], attempt + 1, type(exc).__name__)
                if runtime or attempt >= self.max_retries:
                    self.store.update_job(job_data["id"], status="failed", error=str(exc), retry_count=retry_offset + attempt)
                    return
                await asyncio.sleep(min(2 ** attempt, 8))
            finally:
                if attempt_id:
                    with self.store.transaction() as db:
                        db.execute("UPDATE generation_attempts SET ended_at=?,status='unknown' WHERE id=? AND ended_at IS NULL", (utc_now(), attempt_id))
