from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_base_url: str
    model_edit: str
    model_draft: str
    max_concurrency: int
    request_timeout: float
    job_timeout: float
    max_retries: int
    data_dir: Path
    database_path: Path
    frontend_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        if not base_url:
            raise RuntimeError("OPENAI_BASE_URL is not set")

        max_concurrency = _int_env("MAX_CONCURRENCY", 3)
        if not 1 <= max_concurrency <= 3:
            raise RuntimeError("MAX_CONCURRENCY must be between 1 and 3")

        return cls(
            openai_api_key=api_key,
            openai_base_url=base_url.rstrip("/"),
            model_edit=os.getenv("MODEL_EDIT", "gpt-image-2.5-sunburst"),
            model_draft=os.getenv("MODEL_DRAFT", "gpt-image-2.5-flare"),
            max_concurrency=max_concurrency,
            request_timeout=_float_env("REQUEST_TIMEOUT", 60),
            job_timeout=_float_env("JOB_TIMEOUT", 240),
            max_retries=_int_env("MAX_RETRIES", 2),
            data_dir=Path(os.getenv("DATA_DIR", "./backend/media")).resolve(),
            database_path=Path(
                os.getenv("DATABASE_PATH", "./backend/data/tasks.db")
            ).resolve(),
            frontend_origins=tuple(
                origin.strip()
                for origin in os.getenv(
                    "FRONTEND_ORIGINS", "http://localhost:5173"
                ).split(",")
                if origin.strip()
            ),
        )
