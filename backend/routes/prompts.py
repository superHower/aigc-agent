from __future__ import annotations

import sqlite3
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from backend.db.task_store import utc_now

router = APIRouter(prefix="/api", tags=["prompt library"])


class CategoryInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称不能为空")
        return value


class TemplateInput(CategoryInput):
    content: str = Field(min_length=1, max_length=32000)
    category_id: str | None = None

    @field_validator("content")
    @classmethod
    def non_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("提示词内容不能为空")
        return value


def connection(request: Request):
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(503, "service is not initialized")
    return store._connect()


def require_row(db, table: str, item_id: str):
    row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "分类或模板不存在，请刷新后重试")
    return dict(row)


@router.get("/prompt-categories")
def list_categories(request: Request):
    with connection(request) as db:
        return {"items": [dict(row) for row in db.execute("SELECT * FROM prompt_categories ORDER BY name, id")]}


@router.post("/prompt-categories", status_code=201)
def create_category(payload: CategoryInput, request: Request):
    with connection(request) as db:
        item_id = uuid4().hex
        try:
            db.execute("INSERT INTO prompt_categories VALUES (?, ?, ?)", (item_id, payload.name, utc_now()))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "分类名称已存在") from exc
        return require_row(db, "prompt_categories", item_id)


@router.put("/prompt-categories/{item_id}")
def update_category(item_id: str, payload: CategoryInput, request: Request):
    with connection(request) as db:
        require_row(db, "prompt_categories", item_id)
        try:
            db.execute("UPDATE prompt_categories SET name = ? WHERE id = ?", (payload.name, item_id))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "分类名称已存在") from exc
        return require_row(db, "prompt_categories", item_id)


@router.delete("/prompt-categories/{item_id}", status_code=204)
def delete_category(item_id: str, request: Request):
    with connection(request) as db:
        require_row(db, "prompt_categories", item_id)
        db.execute("DELETE FROM prompt_categories WHERE id = ?", (item_id,))
    return Response(status_code=204)


@router.get("/prompt-templates")
def list_templates(request: Request, q: str = Query(default="", max_length=200), category_id: str | None = None, uncategorized: bool = False):
    filters, values = [], []
    if q.strip():
        filters.append("(instr(lower(name), lower(?)) > 0 OR instr(lower(content), lower(?)) > 0)")
        values.extend([q.strip(), q.strip()])
    if category_id is not None:
        filters.append("category_id = ?")
        values.append(category_id)
    if uncategorized:
        filters.append("category_id IS NULL")
    where = " WHERE " + " AND ".join(filters) if filters else ""
    with connection(request) as db:
        rows = db.execute("SELECT * FROM prompt_templates" + where + " ORDER BY updated_at DESC, id", values)
        return {"items": [dict(row) for row in rows]}


@router.get("/prompt-templates/{item_id}")
def get_template(item_id: str, request: Request):
    with connection(request) as db:
        return require_row(db, "prompt_templates", item_id)


def save_template(db, payload: TemplateInput, item_id: str, create: bool):
    if payload.category_id is not None:
        require_row(db, "prompt_categories", payload.category_id)
    now = utc_now()
    if create:
        db.execute(
            "INSERT INTO prompt_templates VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, payload.name, payload.content, payload.category_id, now, now),
        )
    else:
        require_row(db, "prompt_templates", item_id)
        db.execute(
            "UPDATE prompt_templates SET name = ?, content = ?, category_id = ?, updated_at = ? WHERE id = ?",
            (payload.name, payload.content, payload.category_id, now, item_id),
        )
    return require_row(db, "prompt_templates", item_id)


@router.post("/prompt-templates", status_code=201)
def create_template(payload: TemplateInput, request: Request):
    with connection(request) as db:
        return save_template(db, payload, uuid4().hex, create=True)


@router.put("/prompt-templates/{item_id}")
def update_template(item_id: str, payload: TemplateInput, request: Request):
    with connection(request) as db:
        return save_template(db, payload, item_id, create=False)


@router.delete("/prompt-templates/{item_id}", status_code=204)
def delete_template(item_id: str, request: Request):
    with connection(request) as db:
        require_row(db, "prompt_templates", item_id)
        db.execute("DELETE FROM prompt_templates WHERE id = ?", (item_id,))
    return Response(status_code=204)
