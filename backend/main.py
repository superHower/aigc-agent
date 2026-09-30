from __future__ import annotations

import logging
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import AsyncOpenAI

from backend.config import Settings
from backend.db.task_store import TaskStore, utc_now
from backend.models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AdvancedEditRequest,
    BatchRequest,
    CancelResponse,
    CreateTaskRequest,
    HealthResponse,
    JobView,
    TaskView,
    UploadFileInfo,
    UploadResponse,
    PromptPreviewRequest,
    PromptPreviewResponse,
)
from backend.services.file_storage import save_source, validate_image_bytes
from backend.services.image_editor import ImageEditor
from backend.services.model_registry import ModelRegistry
from backend.services.task_manager import TaskManager
from backend.services.analyzer import Analyzer
from backend.services.ocr_service import OCRService
from backend.services.prompt_builder import PromptContext, PromptType, build_prompt
from backend.services.mask_generator import create_background_mask, create_mask

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for directory in ("source", "output", "masks", "snapshots"):
        (settings.data_dir / directory).mkdir(parents=True, exist_ok=True)
    store = TaskStore(settings.database_path)
    store.recover_processing()
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.request_timeout,
    )
    registry = ModelRegistry(client, settings.model_edit, settings.model_draft)
    await registry.initialize()
    editor = ImageEditor(
        client,
        registry,
        settings.data_dir / "snapshots",
        settings.data_dir / "output",
    )
    manager = TaskManager(
        store,
        editor,
        settings.data_dir,
        settings.request_timeout,
        settings.job_timeout,
        settings.max_retries,
        settings.max_concurrency,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.registry = registry
    app.state.manager = manager
    app.state.analyzer = Analyzer(store, settings.data_dir, OCRService())
    try:
        yield
    finally:
        await client.close()


app = FastAPI(title="ECOM IMAGE STUDIO", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def state(request: Request):
    if not hasattr(request.app.state, "store"):
        raise HTTPException(status_code=503, detail="service is not initialized")
    return request.app.state


@app.get("/api/health", response_model=HealthResponse)
async def health(request: Request):
    current = state(request)
    health_data = current.registry.health()
    health_data["database"] = "ok"
    return health_data


@app.post("/api/upload", response_model=UploadResponse)
async def upload(request: Request, files: list[UploadFile] = File(...)):
    current = state(request)
    if len(files) > 16:
        raise HTTPException(status_code=413, detail="at most 16 files can be uploaded")
    result: list[UploadFileInfo] = []
    for upload_file in files:
        data = await upload_file.read()
        try:
            image, actual_mime = validate_image_bytes(data, upload_file.filename or "upload")
            path = save_source(data, upload_file.filename or "upload", image, current.settings.data_dir)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        file_id = f"src_{uuid4().hex}"
        current.store.register_file(
            {
                "id": file_id,
                "original_name": upload_file.filename or "upload",
                "path": str(path),
                "mime_type": actual_mime,
                "width": image.width,
                "height": image.height,
                "size": len(data),
                "created_at": utc_now(),
            }
        )
        result.append(
            UploadFileInfo(
                file_id=file_id,
                filename=upload_file.filename or "upload",
                url=f"/api/files/{file_id}",
                width=image.width,
                height=image.height,
                size=len(data),
                content_type=actual_mime,
            )
        )
    return UploadResponse(files=result)


@app.post("/api/task/create")
async def create_task(payload: CreateTaskRequest, request: Request):
    current = state(request)
    source = current.store.get_file(payload.file_id)
    if source is None:
        raise HTTPException(status_code=404, detail="file not found")
    try:
        task_id = await current.manager.create_single_job(
            source_id=payload.file_id,
            source_path=Path(source["path"]),
            width=source["width"],
            height=source["height"],
            bbox=(payload.mask.x1, payload.mask.y1, payload.mask.x2, payload.mask.y2),
            prompt=payload.prompt,
            size=payload.size,
            quality=payload.quality,
            output_format=payload.output_format,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"task_id": task_id, "status": "queued", "total_jobs": 1}


@app.post("/api/edit/advanced")
async def advanced_edit(payload: AdvancedEditRequest, request: Request):
    current = state(request)
    source = current.store.get_file(payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source file not found")
    reference = None
    if payload.edit_type == "logo":
        if not payload.reference_file_id:
            raise HTTPException(status_code=422, detail="reference_file_id is required for logo editing")
        reference = current.store.get_file(payload.reference_file_id)
        if reference is None:
            raise HTTPException(status_code=404, detail="reference file not found")
    try:
        if payload.edit_type == "background":
            mask_path = current.settings.data_dir / "masks" / f"background_{uuid4().hex}.png"
            create_background_mask(Path(source["path"]), mask_path)
            prompt_context = PromptContext(prompt_type=PromptType.BACKGROUND, background=payload.background, subject=payload.subject)
        else:
            if payload.mask is None:
                raise ValueError("mask is required for this edit type")
            mask_path = current.settings.data_dir / "masks" / f"{payload.edit_type}_{uuid4().hex}.png"
            create_mask(source["width"], source["height"], (payload.mask.x1, payload.mask.y1, payload.mask.x2, payload.mask.y2), mask_path)
            prompt_context = PromptContext(
                prompt_type=PromptType(payload.edit_type), target=payload.target,
                color=payload.color, bulb=payload.bulb, brand=payload.brand, position=payload.position,
            )
        prompt = build_prompt(prompt_context)
        task_id = await current.manager.create_single_job(
            source_id=payload.source_id, source_path=Path(source["path"]), width=source["width"], height=source["height"],
            bbox=(0, 0, source["width"], source["height"]), prompt=prompt, size=payload.size,
            quality=payload.quality, output_format=payload.output_format, reference_path=Path(reference["path"]) if reference else None,
            mask_path=mask_path,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"task_id": task_id, "status": "queued", "edit_type": payload.edit_type}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest, request: Request):
    current = state(request)
    results = []
    for file_id in payload.file_ids:
        results.append(await asyncio.to_thread(current.analyzer.analyze, file_id))
    return AnalyzeResponse(files=results)


@app.post("/api/generate/batch")
async def generate_batch(payload: BatchRequest, request: Request):
    current = state(request)
    sources = current.store.get_files(payload.source_ids)
    missing = [file_id for file_id in payload.source_ids if file_id not in sources]
    if missing:
        raise HTTPException(status_code=404, detail={"missing_file_ids": missing})

    jobs: list[dict[str, str]] = []
    source_jobs: dict[str, list[dict[str, str]]] = {}
    for source_id in payload.source_ids:
        source = sources[source_id]
        analysis_json = current.store.get_analysis(source_id)
        if not analysis_json:
            raise HTTPException(status_code=409, detail=f"analyze source before generation: {source_id}")
        analysis = AnalyzeResponse.model_validate_json('{"files":[' + analysis_json + ']}').files[0]
        overrides = payload.per_source_overrides.get(source_id, {})
        replacements = {item.id: item for item in overrides.text_blocks}
        source_job_list: list[dict[str, str]] = []
        for block in analysis.text_blocks:
            replacement = replacements.get(block.id)
            if not replacement or not replacement.enabled or not replacement.replace.strip() or replacement.replace.strip() == block.original.strip():
                continue
            mask_id = block.mask_url.rsplit("/", 1)[-1]
            mask_record = current.store.get_file(mask_id)
            if mask_record is None:
                raise HTTPException(status_code=500, detail=f"mask not found: {mask_id}")
            job_id = f"batch_{uuid4().hex}_{source_id}_text_{block.id}"
            prompt = build_prompt(PromptContext(
                prompt_type=PromptType.TEXT,
                original=block.original,
                replace=replacement.replace,
                position=block.position,
            ))
            job = {
                "id": job_id,
                "source_id": source_id,
                "step": f"text_{block.id}",
                "target_id": block.id,
                "prompt": prompt,
                "mask_path": mask_record["path"],
                "input_path": source["path"],
            }
            jobs.append(job)
            source_job_list.append(job)
        source_jobs[source_id] = source_job_list

    if not jobs:
        raise HTTPException(status_code=422, detail="no enabled text replacements were provided")
    task_id = f"task_{uuid4().hex}"
    current.store.create_batch(task_id, payload.source_ids, payload.edit_rule.model_dump(), jobs)
    await current.manager.create_batch(task_id, source_jobs, payload.edit_rule.model_dump())
    return {"task_id": task_id, "status": "queued", "total_jobs": len(jobs), "source_count": len(source_jobs)}


@app.post("/api/prompt/preview", response_model=PromptPreviewResponse)
async def prompt_preview(payload: PromptPreviewRequest):
    try:
        prompt_type = PromptType(payload.prompt_type)
        prompt = build_prompt(PromptContext(
            prompt_type=prompt_type,
            background=payload.background,
            subject=payload.subject,
            target=payload.target,
            color=payload.color,
            bulb=payload.bulb,
            original=payload.original,
            replace=payload.replace,
            position=payload.position,
            brand=payload.brand,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PromptPreviewResponse(prompt_type=payload.prompt_type, prompt=prompt)


def task_view(request: Request, task_id: str) -> TaskView:
    current = state(request)
    task = current.store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    jobs = current.store.get_jobs(task_id)
    views = []
    for job in jobs:
        output_url = (
            f"/api/files/{Path(job['output_path']).name}"
            if job["output_path"]
            else None
        )
        views.append(
            JobView(
                id=job["id"], task_id=job["task_id"], source_id=job["source_id"],
                step=job["step"], target_id=job["target_id"], status=job["status"], retry_count=job["retry_count"],
                cancel_requested=bool(job["cancel_requested"]), input_path=job["input_path"],
                output_path=job["output_path"], output_url=output_url, error=job["error"],
                created_at=job["created_at"], updated_at=job["updated_at"],
            )
        )
    terminal_jobs = sum(job.status in {"done", "failed", "cancelled"} for job in views)
    sources = []
    for source_id in sorted({job.source_id for job in views}):
        source_jobs = [job for job in views if job.source_id == source_id]
        sources.append({
            "source_id": source_id,
            "status": "completed" if all(job.status == "done" for job in source_jobs) else "failed" if any(job.status == "failed" for job in source_jobs) else "cancelled" if all(job.status == "cancelled" for job in source_jobs) else "running",
            "total_jobs": len(source_jobs),
            "completed_jobs": sum(job.status == "done" for job in source_jobs),
        })
    return TaskView(
        id=task["id"], status=task["status"], created_at=task["created_at"],
        updated_at=task["updated_at"], total_jobs=len(jobs),
        completed_jobs=sum(job.status == "done" for job in views),
        failed_jobs=sum(job.status == "failed" for job in views),
        cancelled_jobs=sum(job.status == "cancelled" for job in views),
        progress=terminal_jobs / len(views) if views else 0,
        sources=sources, jobs=views, error=task["error"],
    )


@app.get("/api/task/{task_id}", response_model=TaskView)
async def get_task(task_id: str, request: Request):
    return task_view(request, task_id)


@app.post("/api/task/{task_id}/cancel", response_model=CancelResponse)
async def cancel_task(task_id: str, request: Request):
    current = state(request)
    if current.store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    requested, done = current.manager.cancel(task_id)
    task = current.store.get_task(task_id)
    return CancelResponse(
        task_id=task_id,
        status=task["status"] if task else "cancelling",
        cancel_requested_jobs=requested,
        already_done_jobs=done,
    )


@app.get("/api/files/{file_id}")
async def download_file(file_id: str, request: Request):
    current = state(request)
    record = current.store.get_file(file_id)
    if record is not None:
        path = Path(record["path"])
        if path.exists():
            return FileResponse(path, media_type=record["mime_type"], filename=record["original_name"])
    job = current.store.get_job(file_id)
    if job is not None and job["output_path"]:
        output_path = Path(job["output_path"])
        if output_path.exists() and output_path.is_file():
            return FileResponse(output_path)
    output_job = current.store.get_job_by_output_name(file_id)
    if output_job is not None and output_job["output_path"]:
        output_path = Path(output_job["output_path"])
        if output_path.exists() and output_path.is_file():
            return FileResponse(output_path)
    raise HTTPException(status_code=404, detail="file not found")
