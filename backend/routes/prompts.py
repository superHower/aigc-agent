from __future__ import annotations

import sqlite3
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from backend.db.task_store import utc_now
from backend.services.access import current_user

router = APIRouter(prefix="/api", tags=["prompt library"])


class CategoryInput(BaseModel):
    visibility: str = "private"

    @field_validator("visibility")
    @classmethod
    def valid_visibility(cls, value):
        if value not in ("private", "public"):
            raise ValueError("无效的可见范围")
        return value

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


def public_row(row, table):
    result = dict(row)
    if table == 'prompt_categories':
        result['name'] = result.pop('display_name') or result['name']
    return result


def require_row(db, table: str, item_id: str, user, write=False):
    row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is None or (user['role'] != 'admin' and row['owner_id'] != user['id'] and (write or row['visibility'] != 'public')):
        raise HTTPException(404, "分类或模板不存在，请刷新后重试")
    return public_row(row, table)


def scope(user):
    return ("", []) if user['role'] == 'admin' else ("(owner_id=? OR visibility='public')", [user['id']])


def check_visibility(payload, user):
    if payload.visibility == 'public' and user['role'] != 'admin':
        raise HTTPException(403, '只有管理员可以发布公共模板或分类')


@router.get("/prompt-categories")
def list_categories(request: Request):
    with connection(request) as db:
        clause, values = scope(current_user(request))
        return {"items": [public_row(row, 'prompt_categories') for row in db.execute("SELECT * FROM prompt_categories" + (" WHERE " + clause if clause else "") + " ORDER BY display_name, id", values)]}


@router.post("/prompt-categories", status_code=201)
def create_category(payload: CategoryInput, request: Request):
    user = current_user(request)
    check_visibility(payload, user)
    with connection(request) as db:
        item_id = uuid4().hex
        try:
            db.execute("INSERT INTO prompt_categories (id,name,created_at,owner_id,display_name,visibility) VALUES (?, ?, ?, ?, ?, ?)", (item_id, item_id, utc_now(), user["id"], payload.name, payload.visibility))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "分类名称已存在") from exc
        return require_row(db, "prompt_categories", item_id, current_user(request))


@router.put("/prompt-categories/{item_id}")
def update_category(item_id: str, payload: CategoryInput, request: Request):
    check_visibility(payload, current_user(request))
    with connection(request) as db:
        require_row(db, "prompt_categories", item_id, current_user(request), write=True)
        try:
            if payload.visibility == 'private' and db.execute("SELECT 1 FROM prompt_templates WHERE category_id=? AND visibility='public'", (item_id,)).fetchone():
                raise HTTPException(409, '请先将分类中的公共模板移出或设为私有')
            db.execute("UPDATE prompt_categories SET display_name = ?, visibility = ? WHERE id = ?", (payload.name, payload.visibility, item_id))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "分类名称已存在") from exc
        return require_row(db, "prompt_categories", item_id, current_user(request))


@router.delete("/prompt-categories/{item_id}", status_code=204)
def delete_category(item_id: str, request: Request):
    with connection(request) as db:
        require_row(db, "prompt_categories", item_id, current_user(request), write=True)
        db.execute("DELETE FROM prompt_categories WHERE id = ?", (item_id,))
    return Response(status_code=204)


@router.get("/prompt-templates")
def list_templates(request: Request, q: str = Query(default="", max_length=200), category_id: str | None = None, uncategorized: bool = False):
    clause, values = scope(current_user(request))
    filters = [clause] if clause else []
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
        return require_row(db, "prompt_templates", item_id, current_user(request))


def save_template(db, payload: TemplateInput, item_id: str, create: bool, user):
    check_visibility(payload, user)
    if payload.category_id is not None:
        category = require_row(db, "prompt_categories", payload.category_id, user)
        if (category['owner_id'] != user['id'] and category['visibility'] != 'public') or (payload.visibility == 'public' and category['visibility'] != 'public'):
            raise HTTPException(404, '分类不存在或范围不匹配')
    now = utc_now()
    if create:
        db.execute(
            "INSERT INTO prompt_templates (id,name,content,category_id,created_at,updated_at,owner_id,visibility) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, payload.name, payload.content, payload.category_id, now, now, user["id"], payload.visibility),
        )
    else:
        require_row(db, "prompt_templates", item_id, user, write=True)
        db.execute(
            "UPDATE prompt_templates SET name = ?, content = ?, category_id = ?, updated_at = ?, visibility = ? WHERE id = ?",
            (payload.name, payload.content, payload.category_id, now, payload.visibility, item_id),
        )
    return require_row(db, "prompt_templates", item_id, user)


@router.post("/prompt-templates", status_code=201)
def create_template(payload: TemplateInput, request: Request):
    with connection(request) as db:
        return save_template(db, payload, uuid4().hex, create=True, user=current_user(request))


@router.put("/prompt-templates/{item_id}")
def update_template(item_id: str, payload: TemplateInput, request: Request):
    with connection(request) as db:
        return save_template(db, payload, item_id, create=False, user=current_user(request))


@router.delete("/prompt-templates/{item_id}", status_code=204)
def delete_template(item_id: str, request: Request):
    with connection(request) as db:
        require_row(db, "prompt_templates", item_id, current_user(request), write=True)
        db.execute("DELETE FROM prompt_templates WHERE id = ?", (item_id,))
    return Response(status_code=204)
