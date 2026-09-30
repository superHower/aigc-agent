from __future__ import annotations

import logging
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
    CancelResponse,
    CreateTaskRequest,
    HealthResponse,
    JobView,
    TaskView,
    UploadFileInfo,
    UploadResponse,
)
from backend.services.file_storage import save_source, validate_image_bytes
from backend.services.image_editor import ImageEditor
from backend.services.model_registry import ModelRegistry
from backend.services.task_manager import TaskManager

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
    )
    app.state.settings = settings
    app.state.store = store
    app.state.registry = registry
    app.state.manager = manager
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
                step=job["step"], status=job["status"], retry_count=job["retry_count"],
                cancel_requested=bool(job["cancel_requested"]), input_path=job["input_path"],
                output_path=job["output_path"], output_url=output_url, error=job["error"],
                created_at=job["created_at"], updated_at=job["updated_at"],
            )
        )
    return TaskView(
        id=task["id"], status=task["status"], created_at=task["created_at"],
        updated_at=task["updated_at"], total_jobs=len(jobs),
        completed_jobs=sum(job.status == "done" for job in views),
        failed_jobs=sum(job.status == "failed" for job in views),
        cancelled_jobs=sum(job.status == "cancelled" for job in views),
        jobs=views, error=task["error"],
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
