from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MaskRect(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class UploadFileInfo(BaseModel):
    file_id: str
    filename: str
    url: str
    width: int
    height: int
    size: int
    content_type: str


class UploadResponse(BaseModel):
    files: list[UploadFileInfo] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    file_ids: list[str] = Field(min_length=1, max_length=16)


class TextBlockView(BaseModel):
    id: str
    bbox: tuple[int, int, int, int]
    position: str
    original: str
    confidence: float | None = None
    mask_url: str


class AnalyzeFileResult(BaseModel):
    file_id: str
    width: int
    height: int
    thumbnail_url: str | None = None
    logo_blocks: list[dict[str, Any]] = Field(default_factory=list)
    text_blocks: list[TextBlockView] = Field(default_factory=list)
    error: str | None = None


class AnalyzeResponse(BaseModel):
    files: list[AnalyzeFileResult] = Field(default_factory=list)


class CreateTaskRequest(BaseModel):
    file_id: str
    mask: MaskRect
    prompt: str
    size: str = "1024x1024"
    quality: str = "high"
    output_format: str = "png"

    @field_validator("prompt")
    @classmethod
    def prompt_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be empty")
        if len(value) > 32000:
            raise ValueError("prompt must not exceed 32000 characters")
        return value

    @field_validator("size")
    @classmethod
    def validate_size(cls, value: str) -> str:
        if value not in {"1024x1024", "1536x1024", "1024x1536", "auto"}:
            raise ValueError("unsupported size")
        return value

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, value: str) -> str:
        if value not in {"low", "medium", "high", "xhigh", "max", "auto"}:
            raise ValueError("unsupported quality")
        return value

    @field_validator("output_format")
    @classmethod
    def validate_output_format(cls, value: str) -> str:
        if value not in {"png", "jpeg", "webp"}:
            raise ValueError("unsupported output format")
        return value


class JobView(BaseModel):
    id: str
    task_id: str
    source_id: str
    step: str
    status: str
    retry_count: int
    cancel_requested: bool
    input_path: str
    output_path: str
    output_url: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskView(BaseModel):
    id: str
    status: str
    created_at: datetime
    updated_at: datetime
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    jobs: list[JobView] = Field(default_factory=list)
    error: str | None = None


class CancelResponse(BaseModel):
    task_id: str
    status: str
    cancel_requested_jobs: int
    already_done_jobs: int


class HealthResponse(BaseModel):
    status: str
    models: dict[str, Any]
    capabilities: dict[str, str]
    database: str
