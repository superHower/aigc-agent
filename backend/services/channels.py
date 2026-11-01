from __future__ import annotations

import asyncio
from contextlib import suppress
from contextlib import nullcontext
from dataclasses import dataclass, field
from uuid import uuid4

from openai import AsyncOpenAI
from httpx import TransportError
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
    estimated_cost_cents: int | None = Field(default=None, strict=True, ge=0, le=1000000)

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
                CREATE TABLE IF NOT EXISTS task_channel_failures (
                    task_id TEXT NOT NULL, channel_id TEXT NOT NULL, error TEXT NOT NULL,
                    PRIMARY KEY (task_id, channel_id)
                );
            """)
            from backend.db.migrations import columns
            if 'estimated_cost_cents' not in columns(connection, 'channels'):
                connection.execute('ALTER TABLE channels ADD COLUMN estimated_cost_cents INTEGER')

    def seed(self, settings) -> None:
        with self.store._connect() as connection:
            if connection.execute("SELECT 1 FROM channel_metadata WHERE key = 'seeded'").fetchone():
                return
            if settings.openai_api_key and settings.openai_base_url and not self.list():
                self.save(ChannelInput(name="默认渠道", model=settings.model_edit,
                                       base_url=settings.openai_base_url, api_key=settings.openai_api_key,
                                       concurrency=3))
            connection.execute("INSERT INTO channel_metadata VALUES ('seeded') ON CONFLICT (key) DO NOTHING")

    def list(self) -> list[dict]:
        with self.store._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM channels ORDER BY created_at, rowid")]

    @staticmethod
    def public(row: dict) -> dict:
        return {key: value for key, value in row.items() if key != "api_key"} | {"has_api_key": bool(row["api_key"])}

    def save(self, payload: ChannelInput, channel_id: str | None = None, actor_id=None) -> dict:
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
            connection.execute(f"INSERT INTO channels ({','.join(names)}) VALUES ({','.join('?' for _ in names)}) ON CONFLICT (id) DO UPDATE SET " + ','.join(f"{name}=excluded.{name}" for name in names if name != "id"), tuple(row.values()))
            if actor_id:
                from backend.services.audit import log
                # Never include keys, request addresses or upstream payloads in audit summaries.
                log(connection, actor_id, 'channel_save', row['id'], {k: row[k] for k in ('name', 'model', 'concurrency', 'timeout', 'enabled', 'estimated_cost_cents')})
        return self.public(row)

    def delete(self, channel_id: str, actor_id=None) -> None:
        with self.store._connect() as connection:
            if not connection.execute("DELETE FROM channels WHERE id = ?", (channel_id,)).rowcount:
                raise LookupError("渠道不存在")
            if actor_id:
                from backend.services.audit import log
                log(connection, actor_id, 'channel_delete', channel_id)

    def reset(self, channel_id: str, actor_id=None) -> None:
        with self.store._connect() as connection:
            if not connection.execute("UPDATE channels SET last_error = NULL, updated_at = ? WHERE id = ?", (utc_now(), channel_id)).rowcount:
                raise LookupError("渠道不存在")
            if actor_id:
                from backend.services.audit import log
                log(connection, actor_id, 'channel_reset', channel_id)

    def available(self, task_id: str | None = None) -> list[dict]:
        excluded = set()
        if task_id:
            with self.store._connect() as connection:
                excluded = {row['channel_id'] for row in connection.execute('SELECT channel_id FROM task_channel_failures WHERE task_id=?', (task_id,))}
        return [row for row in self.list() if row["enabled"] and not row["last_error"] and row['id'] not in excluded]


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
    task_id: str | None = None


class ChannelPool:
    def __init__(self, store: ChannelStore, data_dir):
        self.store = store
        self.data_dir = data_dir
        self.runtimes: dict[tuple[str, ...], ChannelRuntime] = {}

    def snapshot(self, task_id: str | None = None) -> list[ChannelRuntime]:
        result = []
        for row in self.store.available(task_id):
            key = (row["id"], row["updated_at"])
            if key not in self.runtimes:
                client = AsyncOpenAI(api_key=row["api_key"], base_url=row["base_url"], max_retries=0, timeout=row["timeout"])
                editor = ImageEditor(client, FixedModel(row["model"]), self.data_dir / "snapshots", self.data_dir / "output")
                self.runtimes[key] = ChannelRuntime(row, editor, asyncio.Semaphore(row["concurrency"]))
            runtime = self.runtimes[key]
            if task_id:
                task_key = (*key, task_id)
                if task_key not in self.runtimes:
                    self.runtimes[task_key] = ChannelRuntime(row, runtime.editor, runtime.semaphore, task_id=task_id)
                runtime = self.runtimes[task_key]
            result.append(runtime)
        return result

    async def close(self):
        closed = set()
        for runtime in self.runtimes.values():
            if id(runtime.editor) not in closed:
                await runtime.editor.client.close()
                closed.add(id(runtime.editor))

    def release_task(self, task_id: str):
        for key in list(self.runtimes):
            if len(key) == 3 and key[2] == task_id:
                del self.runtimes[key]

    def trip(self, runtime: ChannelRuntime, exc: Exception):
        if runtime.broken.is_set():
            return
        # Never persist raw upstream messages: they may contain credentials or request bodies.
        status = getattr(exc, "status_code", None)
        body = getattr(exc, 'body', None)
        # Inspect upstream details only for classification; never store or expose them.
        details = (str(body) + ' ' + str(exc)).lower()
        insufficient = status == 402 or any(token in details for token in (
            'insufficient_quota', 'insufficient_balance', 'insufficient balance', 'insufficient funds',
            'credit balance is too low', 'quota exhausted', 'balance exhausted', '余额不足', '余额已耗尽', '欠费',
        ))
        network = not insufficient and (
            isinstance(exc, (TimeoutError, ConnectionError, TransportError))
            or any(token in type(exc).__name__ for token in ('Timeout', 'Connection', 'Network', 'Transport', 'Protocol'))
            or status in (408, 500, 502, 503, 504, 522, 524)
            or any(token in details for token in ('timed out', 'timeout', 'connection reset', 'connection refused', 'network error', '网络异常', '网络波动', '连接超时'))
        )
        reason = "余额不足" if insufficient else "请求超时或网络异常" if network else {
            401: "API Key 无效", 403: "访问被拒绝或余额不足", 402: "余额不足", 429: "额度不足或请求受限",
        }.get(status, f"上游服务异常（HTTP {status}）" if status else "上游未返回有效图片")
        runtime.error = f"渠道「{runtime.config['name']}」异常：{reason}；" + ("当前任务及其后续重试不再使用此渠道，新任务仍可使用。" if network else "已停止使用，请检查配置后恢复渠道。")
        runtime.broken.set()
        with self.store.store._connect() as connection:
            if network:
                if runtime.task_id:
                    connection.execute('INSERT INTO task_channel_failures (task_id,channel_id,error) VALUES (?,?,?) ON CONFLICT (task_id,channel_id) DO NOTHING', (runtime.task_id, runtime.config['id'], runtime.error))
            else:
                changed = connection.execute("UPDATE channels SET last_error = ? WHERE id = ? AND updated_at = ?",
                                   (runtime.error, runtime.config["id"], runtime.config["updated_at"])).rowcount
                if changed:
                    for other in self.runtimes.values():
                        if other.config['id'] == runtime.config['id'] and other.config['updated_at'] == runtime.config['updated_at']:
                            other.error = runtime.error
                            other.broken.set()

    async def edit(self, runtime: ChannelRuntime, on_start=None, capacity_reserved=False, **kwargs):
        async with (nullcontext() if capacity_reserved else runtime.semaphore):
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
