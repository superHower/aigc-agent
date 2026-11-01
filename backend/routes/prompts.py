from __future__ import annotations

import sqlite3
from io import BytesIO
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, ValidationError, field_validator
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font

from backend.db.task_store import utc_now
from backend.services.access import current_user
from backend.services.audit import log
from backend.services.prompt_groups import group_view

router = APIRouter(prefix="/api", tags=["prompt library"])
EXCEL_HEADERS = ("模板名称", "分类", "提示词内容")


class GroupInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    template_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator('name')
    @classmethod
    def non_blank(cls, value):
        if not value.strip():
            raise ValueError('名称不能为空')
        return value.strip()

    @field_validator('template_ids')
    @classmethod
    def unique_members(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('组内模板不能重复')
        return value


@router.get('/prompt-groups')
def list_groups(request: Request):
    user = current_user(request)
    with connection(request) as db:
        rows = db.execute('SELECT id FROM prompt_groups WHERE owner_id=? ORDER BY updated_at DESC, id', (user['id'],)).fetchall()
        return {'items': [group_view(db, row['id'], user) for row in rows]}


def save_group(payload, request, item_id=None):
    user = current_user(request)
    with connection(request) as db:
        if item_id:
            group_view(db, item_id, user)
        for template_id in payload.template_ids:
            require_row(db, 'prompt_templates', template_id, user)
        now = utc_now()
        try:
            if item_id:
                db.execute('UPDATE prompt_groups SET name=?,updated_at=? WHERE id=?', (payload.name, now, item_id))
                db.execute('DELETE FROM prompt_group_members WHERE group_id=?', (item_id,))
            else:
                item_id = uuid4().hex
                db.execute('INSERT INTO prompt_groups (id,owner_id,name,created_at,updated_at) VALUES (?,?,?,?,?)', (item_id, user['id'], payload.name, now, now))
            for position, template_id in enumerate(payload.template_ids):
                db.execute('INSERT INTO prompt_group_members (group_id,template_id,position) VALUES (?,?,?)', (item_id, template_id, position))
            log(db, user['id'], 'prompt_group_save', item_id, payload.model_dump())
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, '提示词组名称已存在或模板已变更，请刷新后重试') from exc
        return group_view(db, item_id, user)


@router.post('/prompt-groups', status_code=201)
def create_group(payload: GroupInput, request: Request):
    return save_group(payload, request)


@router.put('/prompt-groups/{item_id}')
def update_group(item_id: str, payload: GroupInput, request: Request):
    return save_group(payload, request, item_id)


@router.delete('/prompt-groups/{item_id}', status_code=204)
def delete_group(item_id: str, request: Request):
    user = current_user(request)
    with connection(request) as db:
        group_view(db, item_id, user)
        db.execute('DELETE FROM prompt_groups WHERE id=?', (item_id,))
        log(db, user['id'], 'prompt_group_delete', item_id)
    return Response(status_code=204)


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
            log(db, user['id'], 'category_create', item_id, payload.model_dump())
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
            log(db, current_user(request)['id'], 'category_update', item_id, payload.model_dump())
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "分类名称已存在") from exc
        return require_row(db, "prompt_categories", item_id, current_user(request))


@router.delete("/prompt-categories/{item_id}", status_code=204)
def delete_category(item_id: str, request: Request):
    with connection(request) as db:
        require_row(db, "prompt_categories", item_id, current_user(request), write=True)
        db.execute("DELETE FROM prompt_categories WHERE id = ?", (item_id,))
        log(db, current_user(request)['id'], 'category_delete', item_id)
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
    log(db, user['id'], 'template_create' if create else 'template_update', item_id, {'name': payload.name, 'visibility': payload.visibility, 'category_id': payload.category_id})
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
        log(db, current_user(request)['id'], 'template_delete', item_id)
    return Response(status_code=204)


@router.get("/prompt-library/export")
def export_templates(request: Request, q: str = Query(default="", max_length=200), category_id: str | None = None, uncategorized: bool = False):
    templates = list_templates(request, q, category_id, uncategorized)["items"]
    categories = {item["id"]: item["name"] for item in list_categories(request)["items"]}
    book = Workbook()
    sheet = book.active
    sheet.title = "提示词模板"
    sheet.append(EXCEL_HEADERS)
    for item in templates:
        sheet.append([item["name"], categories.get(item["category_id"], ""), item["content"]])
        for cell in sheet[sheet.max_row]:
            cell.data_type = "s"
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for column, width in (("A", 28), ("B", 22), ("C", 100)):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    book.save(output)
    book.close()
    return Response(output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="prompt-templates.xlsx"'})


@router.post("/prompt-library/import")
def import_templates(request: Request, file: UploadFile = File(...)):
    user = current_user(request)
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(422, "请选择 .xlsx 格式的 Excel 文件")
    content = file.file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(422, "Excel 文件不能超过 5 MB")
    try:
        book = load_workbook(BytesIO(content), read_only=True, data_only=False)
    except Exception as exc:
        raise HTTPException(422, "无法读取 Excel，请确认文件是有效的 .xlsx 文件") from exc
    entries = []
    try:
        sheet = book.active
        rows = sheet.iter_rows(max_row=1002, max_col=3)
        header = next(rows, ())
        if tuple(cell.value for cell in header) != EXCEL_HEADERS:
            raise HTTPException(422, "首行须依次为：模板名称、分类、提示词内容。可先导出 Excel 作为导入模板")
        for row_number, cells in enumerate(rows, 2):
            values = [cell.value for cell in cells]
            if all(value is None or value == "" for value in values):
                continue
            if row_number > 1001 or (sheet.max_row or 0) > 1001:
                raise HTTPException(422, "每次最多导入 1000 行，请拆分文件")
            if any(cell.data_type == "f" for cell in cells):
                raise HTTPException(422, f"第 {row_number} 行含公式，请改为纯文本")
            name, category, prompt = [str(value) if value is not None else "" for value in values]
            try:
                payload = TemplateInput(name=name, content=prompt)
                category = CategoryInput(name=category).name if category.strip() else ""
            except ValidationError as exc:
                raise HTTPException(422, f"第 {row_number} 行：{exc.errors()[0]['msg']}") from exc
            entries.append((payload, category))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "无法读取 Excel 内容，请重新保存为 .xlsx 后重试") from exc
    finally:
        book.close()
    if not entries:
        raise HTTPException(422, "Excel 中没有可导入的模板")
    created_categories = 0
    with connection(request) as db:
        existing = db.execute("SELECT id, display_name FROM prompt_categories WHERE owner_id=?", (user["id"],)).fetchall()
        categories = {row["display_name"]: row["id"] for row in existing}
        for payload, category in entries:
            if category and category not in categories:
                ident = uuid4().hex
                db.execute("INSERT INTO prompt_categories (id,name,created_at,owner_id,display_name,visibility) VALUES (?,?,?,?,?,'private')", (ident, ident, utc_now(), user["id"], category))
                categories[category] = ident
                created_categories += 1
                log(db, user["id"], "category_create", ident, {"name": category, "visibility": "private"})
            payload.category_id = categories.get(category)
            save_template(db, payload, uuid4().hex, create=True, user=user)
    return {"imported": len(entries), "created_categories": created_categories}
