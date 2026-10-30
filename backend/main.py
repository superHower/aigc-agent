from __future__ import annotations

import logging
import asyncio
import os
import json
import tempfile
import sqlite3
from zipfile import ZipFile, ZIP_STORED
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.background import BackgroundTask
from openai import AsyncOpenAI

from backend.config import Settings
from backend.routes.prompts import router as prompts_router
from backend.routes.channels import router as channels_router
from backend.routes.dashboard import router as dashboard_router
from backend.routes.auth import router as auth_router, account, csrf_valid
from backend.routes.admin import router as admin_router
from backend.routes.accounts import router as accounts_router
from backend.services import credits
from backend.services.access import current_user, require_file, require_task, visible_job
from backend.services.channels import ChannelStore, ChannelPool
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
    CompositeRequest,
    CompositeResponse,
    RetryRequest,
    MultiImageRequest,
)
from backend.services.file_storage import save_source, validate_image_bytes
from backend.services.image_editor import ImageEditor
from backend.services.model_registry import ModelRegistry
from backend.services.task_manager import TaskManager
from backend.services.analyzer import Analyzer
from backend.services.ocr_service import OCRService
from backend.services.prompt_builder import PromptContext, PromptType, build_prompt
from backend.services.mask_generator import create_background_mask, create_mask
from backend.services.compositor import CompositeError, compose_images
from backend.services.multi_image import plan_multi_image, safe_stem

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for directory in ("source", "output", "masks", "snapshots"):
        (settings.data_dir / directory).mkdir(parents=True, exist_ok=True)
    store = TaskStore(settings.database_url or settings.database_path)
    store.recover_processing()
    channels = ChannelStore(store)
    channels.seed(settings)
    channel_pool = ChannelPool(channels, settings.data_dir)
    client = AsyncOpenAI(
        api_key=settings.openai_api_key or "unconfigured",
        base_url=settings.openai_base_url or "http://127.0.0.1:1/v1",
        timeout=settings.request_timeout,
        max_retries=0,
    )
    registry = ModelRegistry(client, settings.model_edit, settings.model_draft)
    if settings.openai_api_key and settings.openai_base_url:
        try:
            await registry.initialize()
        except RuntimeError:
            logger.warning("Default model discovery unavailable; channel management remains available")
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
        channel_pool=channel_pool,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.channels = channels
    app.state.registry = registry
    app.state.manager = manager
    app.state.analyzer = Analyzer(store, settings.data_dir, OCRService())
    await manager.resume_active_tasks()
    try:
        yield
    finally:
        for worker in list(manager.running_tasks.values()):
            worker.cancel()
        await asyncio.gather(*list(manager.running_tasks.values()), return_exceptions=True)
        await channel_pool.close()
        await client.close()


app = FastAPI(title="ECOM IMAGE STUDIO", version="0.1.0", lifespan=lifespan)
app.include_router(prompts_router)
app.include_router(channels_router)
app.include_router(dashboard_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(accounts_router)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    return JSONResponse({'detail': '输入格式不正确，请检查填写内容'}, status_code=422)


@app.middleware('http')
async def migration_access(request: Request, call_next):
    path = request.url.path
    if path.startswith('/api/') and request.method != 'OPTIONS':
        if path == '/api/health':
            return JSONResponse({'status': 'ok'})
        if path in ('/api/auth/login', '/api/auth/sms', '/api/auth/register', '/api/auth/reset-password'):
            origin = request.headers.get('origin')
            allowed = os.getenv('FRONTEND_ORIGINS', 'http://localhost:5173').split(',')
            if origin and origin not in [v.strip() for v in allowed] and origin != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': '请求来源不允许'}, status_code=403)
        else:
            user = account(request)
            if user is None:
                return JSONResponse({'detail': '请先登录'}, status_code=401)
            request.state.user = user
            if user['role'] != 'admin' and (path.startswith(('/api/channels', '/api/admin/', '/api/edit/')) or path in ('/api/task/create', '/api/generate/batch')):
                return JSONResponse({'detail': '此功能尚未向普通用户开放，未扣除积分'}, status_code=403)
            if request.method not in ('GET', 'HEAD') and not csrf_valid(request, user):
                return JSONResponse({'detail': 'CSRF 校验失败，请刷新后重试'}, status_code=403)
    return await call_next(request)
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
    if len(files) > 50:
        raise HTTPException(status_code=413, detail="at most 50 files can be uploaded")
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
                "owner_id": current_user(request)["id"],
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
    for file_id in payload.file_ids:
        require_file(request, file_id, purposes={"source"})
    results = []
    for file_id in payload.file_ids:
        result = await asyncio.to_thread(current.analyzer.analyze, file_id)
        if current_user(request)['role'] != 'admin' and result.error:
            result.error = '文字识别暂不可用，请稍后重试；未扣除积分'
        results.append(result)
    return AnalyzeResponse(files=results)


@app.post("/api/generate/batch")
async def generate_batch(payload: BatchRequest, request: Request):
    current = state(request)
    sources = current.store.get_files(payload.source_ids)
    missing = [file_id for file_id in payload.source_ids if file_id not in sources]
    if missing:
        raise HTTPException(status_code=404, detail={"missing_file_ids": missing})

    reference_paths: list[str] = []
    for reference_id in payload.edit_rule.reference_file_ids:
        reference = current.store.get_file(reference_id)
        if reference is None:
            raise HTTPException(status_code=404, detail=f"reference file not found: {reference_id}")
        reference_paths.append(reference["path"])
    if payload.edit_rule.logo_replace_enabled and payload.edit_rule.logo_reference_file_id:
        logo_reference = current.store.get_file(payload.edit_rule.logo_reference_file_id)
        if logo_reference is None:
            raise HTTPException(status_code=404, detail="logo reference file not found")
        if logo_reference["path"] not in reference_paths:
            reference_paths.append(logo_reference["path"])

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
        blocks = analysis.text_blocks if payload.edit_rule.text_replace_enabled else []
        for block in blocks:
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
        if payload.edit_rule.logo_replace_enabled and payload.edit_rule.logo_reference_file_id:
            for logo_index, logo in enumerate(analysis.logo_blocks):
                bbox = logo.get("bbox") if isinstance(logo, dict) else None
                if not bbox or len(bbox) != 4:
                    continue
                logo_mask = current.settings.data_dir / "masks" / f"logo_{uuid4().hex}.png"
                create_mask(source["width"], source["height"], tuple(bbox), logo_mask)
                job_id = f"batch_{uuid4().hex}_{source_id}_logo_{logo_index + 1}"
                job = {
                    "id": job_id,
                    "source_id": source_id,
                    "step": f"logo_{logo_index + 1}",
                    "target_id": f"logo_{logo_index + 1}",
                    "prompt": build_prompt(PromptContext(
                        prompt_type=PromptType.LOGO,
                        brand=payload.edit_rule.logo_brand or "指定 Logo",
                        position=payload.edit_rule.logo_position,
                    )),
                    "mask_path": str(logo_mask),
                    "input_path": source["path"],
                }
                jobs.append(job)
                source_job_list.append(job)
        if payload.edit_rule.custom_prompt.strip():
            full_mask = current.settings.data_dir / "masks" / f"custom_{uuid4().hex}.png"
            create_mask(source["width"], source["height"], (0, 0, source["width"], source["height"]), full_mask)
            for variant in range(payload.edit_rule.generation_count):
                job_id = f"batch_{uuid4().hex}_{source_id}_custom_{variant + 1}"
                job = {
                    "id": job_id,
                    "source_id": source_id,
                    "step": f"custom_{variant + 1}",
                    "target_id": None,
                    "prompt": payload.edit_rule.custom_prompt.strip(),
                    "mask_path": str(full_mask),
                    "input_path": source["path"],
                }
                jobs.append(job)
                source_job_list.append(job)
        source_jobs[source_id] = source_job_list

    if not jobs:
        raise HTTPException(status_code=422, detail="请填写文字替换或自定义提示词")
    task_id = f"task_{uuid4().hex}"
    rule = payload.edit_rule.model_dump()
    rule["reference_paths"] = reference_paths
    current.store.create_batch(task_id, payload.source_ids, rule, jobs)
    await current.manager.create_batch(task_id, source_jobs, rule)
    return {"task_id": task_id, "status": "queued", "total_jobs": len(jobs), "source_count": len(source_jobs)}


@app.post("/api/generate/multi-image")
async def generate_multi_image(payload: MultiImageRequest, request: Request):
    current = state(request)
    user = current_user(request)
    key = credits.require_key(request) if user['role'] != 'admin' else request.headers.get('Idempotency-Key')
    digest = credits.fingerprint(payload.model_dump())
    if key:
        with current.store.transaction() as db:
            existing = credits.previous(db, user['id'], 'create', key, digest)
        if existing:
            return {'task_id': existing, 'status': current.store.get_task(existing)['status'], 'total_jobs': len(current.store.get_jobs(existing)), 'estimated_cost': 0}
    if user['role'] != 'admin' and payload.ocr_enabled:
        raise HTTPException(403, '文字生图编辑尚未开放；识别免费，未扣除积分')
    file_ids = list(payload.source_ids)
    if payload.reference_file_id:
        file_ids.append(payload.reference_file_id)
    sources = current.store.get_files(file_ids)
    if any(file_id not in sources for file_id in file_ids):
        raise HTTPException(status_code=404, detail="source or reference file not found")
    for file_id in file_ids:
        require_file(request, file_id, purposes={'source', 'output', 'composite'})
    analyses = {}
    if payload.ocr_enabled:
        for source_id in payload.source_ids:
            cached = current.store.get_analysis(source_id)
            if cached:
                analyses[source_id] = AnalyzeResponse.model_validate_json('{"files":[' + cached + ']}').files[0]
    try:
        source_ids, jobs, source_jobs, rule = await asyncio.to_thread(plan_multi_image, payload, sources, analyses, current.settings.data_dir)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    task_id = f"task_{uuid4().hex}"
    task_id, created = current.store.create_batch(task_id, source_ids, rule, jobs, owner_id=user['id'], billable=user['role'] != 'admin', key=key, digest=digest)
    if created:
        await current.manager.create_batch(task_id, source_jobs, rule)
    return {"task_id": task_id, "status": "queued", "total_jobs": len(jobs), "required_credits": sum(bool(o.get('variant')) for o in rule['outputs'].values()) if user['role'] != 'admin' else 0, "estimated_cost": round(len(jobs) * 0.05, 2) if user['role'] == 'admin' else 0}


@app.post('/api/generate/preview')
async def generation_preview(payload: MultiImageRequest, request: Request):
    ids = payload.source_ids + ([payload.reference_file_id] if payload.reference_file_id else [])
    for file_id in ids:
        require_file(request, file_id, purposes={'source', 'output', 'composite'})
    count = len(payload.source_ids) * len(payload.aspect_ratios)
    user = current_user(request)
    available = credits.balance(state(request).store, user['id'])['available']
    return {'images': count, 'required_credits': count if user['role'] != 'admin' else 0, 'available': available}


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


@app.post("/api/composite", response_model=CompositeResponse)
async def composite(payload: CompositeRequest, request: Request):
    current = state(request)
    paths: list[Path] = []
    for image_id in payload.image_ids:
        record = current.store.get_file(image_id)
        if record is not None:
            require_file(request, image_id, purposes={"source", "output", "composite"})
        else:
            visible_job(request, current.store.get_job_by_output_name(image_id))
    output_names = [image_id for image_id in payload.image_ids if "." in image_id]
    output_paths = current.store.get_done_output_paths(output_names)
    for image_id in payload.image_ids:
        record = current.store.get_file(image_id)
        if record is not None:
            paths.append(Path(record["path"]))
            continue
        output_path = output_paths.get(image_id)
        if output_path is None:
            job = current.store.get_job_by_output_name(image_id)
            output_path = Path(job["output_path"]) if job and job["output_path"] else None
        if output_path is None:
            raise HTTPException(status_code=404, detail=f"image not found: {image_id}")
        paths.append(output_path)
    file_id = f"composite_{uuid4().hex}"
    output_path = current.settings.data_dir / "composite" / f"{file_id}.png"
    try:
        width, height = await asyncio.to_thread(
            compose_images,
            paths,
            output_path,
            width=payload.width,
            gap=payload.gap,
            background_color=payload.background_color,
            padding_top=payload.padding_top,
            padding_bottom=payload.padding_bottom,
        )
    except CompositeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    current.store.register_file({
        "id": file_id,
        "owner_id": current_user(request)["id"],
        "original_name": f"{file_id}.png",
        "path": str(output_path),
        "mime_type": "image/png",
        "width": width,
        "height": height,
        "size": output_path.stat().st_size,
        "created_at": utc_now(),
    })
    return CompositeResponse(file_id=file_id, url=f"/api/files/{file_id}", width=width, height=height, image_count=len(paths))


def task_view(request: Request, task_id: str) -> TaskView:
    current = state(request)
    try:
        task = require_task(request, task_id)
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            raise HTTPException(status_code=503, detail="任务数据库尚未初始化，请重启后端") from exc
        raise
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    jobs = current.store.get_jobs(task_id)
    rule = json.loads(task["edit_rule"])
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
                output_filename=rule.get("outputs", {}).get(job["id"], {}).get("filename"),
                created_at=job["created_at"], updated_at=job["updated_at"],
                channel_name=job["channel_name"],
            )
        )
    if current_user(request)['role'] != 'admin':
        for view in views:
            view.channel_name = None
            view.input_path = ''
            view.output_path = ''
            if view.error:
                view.error = '图片处理未完成；未额外扣除积分，请稍后重试'
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
        credit_summary=task_credit_summary(current.store, task_id),
        auto_retry_count=task["auto_retry_count"],
        id=task["id"], status=task["status"], created_at=task["created_at"],
        updated_at=task["updated_at"], total_jobs=len(jobs),
        completed_jobs=sum(job.status == "done" for job in views),
        failed_jobs=sum(job.status == "failed" for job in views),
        cancelled_jobs=sum(job.status == "cancelled" for job in views),
        progress=terminal_jobs / len(views) if views else 0,
        sources=sources, jobs=views, error=task["error"] if current_user(request)["role"] == "admin" else ("任务未完成，请稍后重试" if task["error"] else None),
        channel_errors=list(dict.fromkeys(job.error for job in views if job.error and job.error.startswith("渠道「"))),
        estimated_cost=round(len(jobs) * 0.05, 2) if current_user(request)["role"] == "admin" else 0, max_concurrency=sum(row["concurrency"] for row in current.channels.available()) if hasattr(current, "channels") else current.settings.max_concurrency,
    )


def task_credit_summary(store, task_id):
    with store.transaction() as db:
        rows = db.execute('''SELECT r.state,COUNT(*) AS amount FROM credit_reservations r JOIN jobs j ON j.id=r.job_id
            WHERE j.task_id=? GROUP BY r.state''', (task_id,)).fetchall()
    return {row['state']: row['amount'] for row in rows}


@app.get("/api/task/{task_id}", response_model=TaskView)
async def get_task(task_id: str, request: Request):
    return task_view(request, task_id)


@app.get("/api/tasks")
async def list_tasks(request: Request, limit: int = 50, offset: int = 0):
    current = state(request)
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(status_code=422, detail="invalid pagination")
    items = []
    user = current_user(request)
    for task in current.store.list_tasks(limit=limit, offset=offset, owner_id=user["id"] if user["role"] != "admin" else None):
        view = task_view(request, task["id"])
        items.append(view.model_dump(mode="json"))
    return {"items": items, "limit": limit, "offset": offset}


@app.get("/api/task/{task_id}/download")
async def download_task(task_id: str, request: Request):
    current = state(request)
    task = require_task(request, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    outputs = json.loads(task["edit_rule"]).get("outputs", {})
    jobs = [job for job in current.store.get_jobs(task_id) if job["status"] == "done" and job["output_path"] and (not outputs or outputs.get(job["id"], {}).get("variant"))]
    if not jobs:
        raise HTTPException(status_code=409, detail="暂无可下载的生成结果")

    def make_archive():
        descriptor, name = tempfile.mkstemp(suffix=".zip")
        os.close(descriptor)
        archive_path = Path(name)
        try:
            with ZipFile(archive_path, "w", compression=ZIP_STORED) as archive:
                used_names = set()
                for job in jobs:
                    filename = outputs.get(job["id"], {}).get("filename", f"{job['id']}.png")
                    if filename in used_names:
                        filename = f"{safe_stem(filename)}-{job['id']}.png"
                    used_names.add(filename)
                    archive.write(job["output_path"], arcname=filename)
            return archive_path
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise

    archive_path = await asyncio.to_thread(make_archive)
    return FileResponse(archive_path, media_type="application/zip", filename=f"{task_id}.zip", background=BackgroundTask(archive_path.unlink, missing_ok=True))


@app.post("/api/task/{task_id}/retry")
async def retry_task(task_id: str, payload: RetryRequest, request: Request):
    current = state(request)
    task = require_task(request, task_id)
    user = current_user(request)
    if task['billable'] or user['role'] != 'admin':
        created = credits.retry(current.store, task['owner_id'], task_id, payload.job_id, credits.require_key(request))
        if created:
            jobs = current.store.get_jobs(task_id)
            chains = {}
            for job in jobs:
                chains.setdefault(job['source_id'], []).append(dict(job))
            await current.manager.create_batch(task_id, chains, json.loads(current.store.get_task(task_id)['edit_rule']))
        return {'task_id': task_id, 'status': current.store.get_task(task_id)['status']}
    try:
        await current.manager.retry(task_id, payload.job_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"task_id": task_id, "status": "queued"}


@app.post("/api/task/{task_id}/cancel", response_model=CancelResponse)
async def cancel_task(task_id: str, request: Request):
    current = state(request)
    if require_task(request, task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    requested, done = current.manager.cancel(task_id)
    task = require_task(request, task_id)
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
        require_file(request, file_id)
        path = Path(record["path"])
        if path.exists():
            return FileResponse(path, media_type=record["mime_type"], filename=record["original_name"])
    job = current.store.get_job(file_id)
    if job is not None and job["output_path"]:
        visible_job(request, job)
        output_path = Path(job["output_path"])
        if output_path.exists() and output_path.is_file():
            return FileResponse(output_path)
    output_job = current.store.get_job_by_output_name(file_id)
    if output_job is not None and output_job["output_path"]:
        visible_job(request, output_job)
        output_path = Path(output_job["output_path"])
        if output_path.exists() and output_path.is_file():
            return FileResponse(output_path)
    raise HTTPException(status_code=404, detail="file not found")
