from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


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
    database_url: str | None = None
    frontend_origins: tuple[str, ...] = ()
    ordinary_concurrency: int = 1
    member_concurrency: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        api_key = api_key or ""
        base_url = base_url or ""

        max_concurrency = _int_env("MAX_CONCURRENCY", 10)
        if not 1 <= max_concurrency <= 20:
            raise RuntimeError("MAX_CONCURRENCY must be between 1 and 20")
        ordinary = _int_env('USER_CONCURRENCY', 1)
        member = _int_env('MEMBER_CONCURRENCY', 3)
        if not 1 <= ordinary <= member <= 20:
            raise RuntimeError('Concurrency must satisfy 1 <= USER_CONCURRENCY <= MEMBER_CONCURRENCY <= 20')

        return cls(
            openai_api_key=api_key,
            openai_base_url=base_url.rstrip("/"),
            model_edit=os.getenv("MODEL_EDIT", "gpt-image-2.5-sunburst"),
            model_draft=os.getenv("MODEL_DRAFT", "gpt-image-2.5-flare"),
            max_concurrency=max_concurrency,
            ordinary_concurrency=ordinary,
            member_concurrency=member,
            request_timeout=_float_env("REQUEST_TIMEOUT", 300),
            job_timeout=_float_env("JOB_TIMEOUT", 360),
            max_retries=_int_env("MAX_RETRIES", 2),
            data_dir=Path(os.getenv("DATA_DIR", "./backend/media")).resolve(),
            database_path=Path(
                os.getenv("DATABASE_PATH", "./backend/data/tasks.db")
            ).resolve(),
            database_url=os.getenv("DATABASE_URL") or None,
            frontend_origins=tuple(
                origin.strip()
                for origin in os.getenv(
                    "FRONTEND_ORIGINS", "http://localhost:5173"
                ).split(",")
                if origin.strip()
            ),
        )
