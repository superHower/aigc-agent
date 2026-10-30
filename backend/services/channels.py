from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from uuid import uuid4

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.db.task_store import TaskStore, utc_now
from backend.services.image_editor import ImageEditor


class ChannelInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2000)
    api_key: str = Field(default="", max_length=2000)
    remark: str = Field(default="", max_length=2000)
    concurrency: int = Field(default=3, ge=1, le=20)
    timeout: int = Field(default=30, ge=1, le=300)
    enabled: bool = True

    @field_validator("name", "model", "base_url", "api_key", "remark")
    @classmethod
    def trim(cls, value: str) -> str:
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("请输入有效的 HTTP(S) API 地址，不要包含密钥、查询参数或片段")
        return value.rstrip("/")


class ChannelStore:
    def __init__(self, store: TaskStore):
        self.store = store
        with store._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS channels (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, model TEXT NOT NULL,
                    base_url TEXT NOT NULL, api_key TEXT NOT NULL, remark TEXT NOT NULL,
                    concurrency INTEGER NOT NULL, timeout INTEGER NOT NULL,
                    enabled INTEGER NOT NULL, last_error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS channel_metadata (key TEXT PRIMARY KEY);
            """)

    def seed(self, settings) -> None:
        with self.store._connect() as connection:
            if connection.execute("SELECT 1 FROM channel_metadata WHERE key = 'seeded'").fetchone():
                return
            if settings.openai_api_key and settings.openai_base_url and not self.list():
                self.save(ChannelInput(name="默认渠道", model=settings.model_edit,
                                       base_url=settings.openai_base_url, api_key=settings.openai_api_key,
                                       concurrency=3))
            connection.execute("INSERT OR IGNORE INTO channel_metadata VALUES ('seeded')")

    def list(self) -> list[dict]:
        with self.store._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM channels ORDER BY created_at, rowid")]

    @staticmethod
    def public(row: dict) -> dict:
        return {key: value for key, value in row.items() if key != "api_key"} | {"has_api_key": bool(row["api_key"])}

    def save(self, payload: ChannelInput, channel_id: str | None = None) -> dict:
        old = next((row for row in self.list() if row["id"] == channel_id), None)
        if channel_id and old is None:
            raise LookupError("渠道不存在")
        values = payload.model_dump()
        values["api_key"] = values["api_key"] or (old["api_key"] if old else "")
        if not values["api_key"]:
            raise ValueError("请填写 API Key")
        now = utc_now()
        row = {"id": channel_id or f"ch_{uuid4().hex}", **values, "last_error": None,
               "created_at": old["created_at"] if old else now, "updated_at": now}
        with self.store._connect() as connection:
            names = list(row)
            connection.execute(f"INSERT OR REPLACE INTO channels ({','.join(names)}) VALUES ({','.join('?' for _ in names)})", tuple(row.values()))
        return self.public(row)

    def delete(self, channel_id: str) -> None:
        with self.store._connect() as connection:
            if not connection.execute("DELETE FROM channels WHERE id = ?", (channel_id,)).rowcount:
                raise LookupError("渠道不存在")

    def reset(self, channel_id: str) -> None:
        with self.store._connect() as connection:
            if not connection.execute("UPDATE channels SET last_error = NULL, updated_at = ? WHERE id = ?", (utc_now(), channel_id)).rowcount:
                raise LookupError("渠道不存在")

    def available(self) -> list[dict]:
        return [row for row in self.list() if row["enabled"] and not row["last_error"]]


class FixedModel:
    def __init__(self, model: str):
        self.model = model

    def resolved_model(self, role: str = "edit") -> str:
        return self.model


class ChannelUnavailable(RuntimeError):
    pass


@dataclass
class ChannelRuntime:
    config: dict
    editor: ImageEditor
    semaphore: asyncio.Semaphore
    broken: asyncio.Event = field(default_factory=asyncio.Event)
    error: str = ""


class ChannelPool:
    def __init__(self, store: ChannelStore, data_dir):
        self.store = store
        self.data_dir = data_dir
        self.runtimes: dict[tuple[str, str], ChannelRuntime] = {}

    def snapshot(self) -> list[ChannelRuntime]:
        result = []
        for row in self.store.available():
            key = (row["id"], row["updated_at"])
            if key not in self.runtimes:
                client = AsyncOpenAI(api_key=row["api_key"], base_url=row["base_url"], max_retries=0, timeout=row["timeout"])
                editor = ImageEditor(client, FixedModel(row["model"]), self.data_dir / "snapshots", self.data_dir / "output")
                self.runtimes[key] = ChannelRuntime(row, editor, asyncio.Semaphore(row["concurrency"]))
            result.append(self.runtimes[key])
        return result

    async def close(self):
        for runtime in self.runtimes.values():
            await runtime.editor.client.close()

    def trip(self, runtime: ChannelRuntime, exc: Exception):
        if runtime.broken.is_set():
            return
        # Never persist raw upstream messages: they may contain credentials or request bodies.
        status = getattr(exc, "status_code", None)
        reason = "请求超时或网络异常" if isinstance(exc, (TimeoutError, ConnectionError)) or "Timeout" in type(exc).__name__ or "Connection" in type(exc).__name__ else {
            401: "API Key 无效", 403: "访问被拒绝或余额不足", 402: "余额不足", 429: "额度不足或请求受限",
        }.get(status, f"上游服务异常（HTTP {status}）" if status else "上游未返回有效图片")
        runtime.error = f"渠道「{runtime.config['name']}」异常：{reason}；已停止使用，请检查配置后恢复渠道。"
        runtime.broken.set()
        with self.store.store._connect() as connection:
            connection.execute("UPDATE channels SET last_error = ? WHERE id = ? AND updated_at = ?",
                               (runtime.error, runtime.config["id"], runtime.config["updated_at"]))

    async def edit(self, runtime: ChannelRuntime, on_start=None, **kwargs):
        async with runtime.semaphore:
            if runtime.broken.is_set():
                raise ChannelUnavailable(runtime.error)
            if on_start is not None and not on_start():
                raise asyncio.CancelledError()
            kwargs["request_timeout"] = runtime.config["timeout"]
            request = asyncio.create_task(runtime.editor.edit(**kwargs))
            stopped = asyncio.create_task(runtime.broken.wait())
            try:
                done, _ = await asyncio.wait({request, stopped}, timeout=runtime.config["timeout"], return_when=asyncio.FIRST_COMPLETED)
                if runtime.broken.is_set():
                    raise ChannelUnavailable(runtime.error)
                if request not in done:
                    raise TimeoutError()
                return request.result()
            except asyncio.CancelledError:
                raise
            except ChannelUnavailable:
                raise
            except Exception as exc:
                self.trip(runtime, exc)
                raise ChannelUnavailable(runtime.error) from None
            finally:
                for task in (request, stopped):
                    task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await task
