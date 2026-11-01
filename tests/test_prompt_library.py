import io

import pytest
from openpyxl import Workbook, load_workbook
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.db.task_store import TaskStore
from backend.routes.prompts import router


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.store = TaskStore(tmp_path / "prompts.sqlite")
    from backend.db.operations import bootstrap_admin
    owner = bootstrap_admin(app.state.store, 'admin', 'test-password-123')
    @app.middleware("http")
    async def admin_context(request, call_next):
        request.state.user = getattr(app.state, 'test_user', {'id': owner, 'role': 'admin'})
        return await call_next(request)
    with TestClient(app) as client:
        yield client


def test_library_crud_filter_and_category_deletion(client):
    category = client.post("/api/prompt-categories", json={"name": "背景替换"}).json()
    category_id = category["id"]
    payload = {"name": "白色背景", "content": "保持产品不变，替换为白色背景。", "category_id": category_id}
    response = client.post("/api/prompt-templates", json=payload)
    assert response.status_code == 201
    template = response.json()
    template_id = template["id"]
    assert client.get(f"/api/prompt-templates/{template_id}").json() == template
    assert client.get("/api/prompt-templates", params={"category_id": category_id, "q": "产品"}).json()["items"] == [template]
    assert client.get("/api/prompt-templates", params={"uncategorized": True}).json()["items"] == []
    assert client.get("/api/prompt-templates", params={"q": "不存在"}).json()["items"] == []
    assert client.put(f"/api/prompt-categories/{category_id}", json={"name": "摄影棚"}).json()["name"] == "摄影棚"
    assert client.put(f"/api/prompt-templates/{template_id}", json={**payload, "content": "改为摄影棚背景"}).json()["content"] == "改为摄影棚背景"
    assert client.delete(f"/api/prompt-categories/{category_id}").status_code == 204
    remaining = client.get("/api/prompt-templates", params={"uncategorized": True}).json()["items"]
    assert remaining[0]["id"] == template_id
    assert remaining[0]["category_id"] is None
    # Reopening the database must preserve saved templates.
    reopened = TaskStore(client.app.state.store.database_path)
    with reopened._connect() as db:
        assert db.execute("SELECT content FROM prompt_templates WHERE id = ?", (template_id,)).fetchone()[0] == "改为摄影棚背景"
    assert client.delete(f"/api/prompt-templates/{template_id}").status_code == 204
    assert client.get(f"/api/prompt-templates/{template_id}").status_code == 404
    assert client.get("/api/prompt-templates").json()["items"] == []


def test_library_rejects_invalid_data(client):
    assert client.post("/api/prompt-categories", json={"name": "   "}).status_code == 422
    assert client.post("/api/prompt-categories", json={"name": " 背景 "}).status_code == 201
    assert client.post("/api/prompt-categories", json={"name": "背景"}).status_code == 409
    assert client.post("/api/prompt-templates", json={"name": "模板", "content": "   "}).status_code == 422
    assert client.post("/api/prompt-templates", json={"name": "模板", "content": "内容", "category_id": "missing"}).status_code == 404
    assert client.put("/api/prompt-templates/missing", json={"name": "模板", "content": "内容"}).status_code == 404
    assert client.delete("/api/prompt-categories/missing").status_code == 404


def excel_file(rows):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_prompt_groups_membership_order_permissions_and_deletion(client):
    first = client.post('/api/prompt-templates', json={'name': '一', 'content': '内容一'}).json()
    second = client.post('/api/prompt-templates', json={'name': '二', 'content': '内容二'}).json()
    payload = {'name': '场景套图', 'template_ids': [second['id'], first['id']]}
    response = client.post('/api/prompt-groups', json=payload)
    assert response.status_code == 201
    group = response.json()
    assert group['template_ids'] == payload['template_ids']
    assert client.post('/api/prompt-groups', json=payload).status_code == 409
    assert client.post('/api/prompt-groups', json={**payload, 'template_ids': [first['id'], first['id']]}).status_code == 422
    assert client.post('/api/prompt-groups', json={'name': '无效', 'template_ids': ['missing']}).status_code == 404
    assert len(client.get('/api/prompt-groups').json()['items']) == 1
    store = client.app.state.store
    from backend.db.task_store import utc_now
    with store.transaction() as db:
        db.execute('INSERT INTO users (id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)', ('other', 'other', 'unused', 'user', utc_now()))
    client.app.state.test_user = {'id': 'other', 'role': 'user'}
    assert client.get('/api/prompt-groups').json()['items'] == []
    assert client.put(f"/api/prompt-groups/{group['id']}", json=payload).status_code == 404
    assert client.delete(f"/api/prompt-groups/{group['id']}").status_code == 404
    assert client.post('/api/prompt-groups', json=payload).status_code == 404
    del client.app.state.test_user
    reordered = {**payload, 'template_ids': [first['id'], second['id']]}
    assert client.put(f"/api/prompt-groups/{group['id']}", json=reordered).json()['template_ids'] == reordered['template_ids']
    assert client.delete(f"/api/prompt-templates/{first['id']}").status_code == 204
    assert client.get('/api/prompt-groups').json()['items'][0]['template_ids'] == [second['id']]
    assert client.delete(f"/api/prompt-groups/{group['id']}").status_code == 204
    assert client.get(f"/api/prompt-templates/{second['id']}").status_code == 200


def test_excel_export_and_import_roundtrip(client):
    category = client.post('/api/prompt-categories', json={'name': '背景', 'visibility': 'public'}).json()
    content = '=保留产品\n调整背景和阴影'
    client.post('/api/prompt-templates', json={'name': '=摄影棚', 'content': content, 'category_id': category['id']})
    client.post('/api/prompt-templates', json={'name': '其他', 'content': '忽略'})
    response = client.get('/api/prompt-library/export', params={'category_id': category['id'], 'q': '摄影棚'})
    assert response.status_code == 200
    book = load_workbook(io.BytesIO(response.content))
    assert list(book.active.values) == [('模板名称', '分类', '提示词内容'), ('=摄影棚', '背景', content)]
    assert book.active['A2'].data_type == 's'
    assert book.active['C2'].data_type == 's'
    book.close()
    imported = client.post('/api/prompt-library/import', files={'file': ('templates.xlsx', response.content)})
    assert imported.status_code == 200
    assert imported.json() == {'imported': 1, 'created_categories': 0}
    templates = client.get('/api/prompt-templates').json()['items']
    assert len(templates) == 3
    assert len([item for item in templates if item['content'] == content and item['visibility'] == 'private']) == 2


def test_excel_import_validates_entire_file_before_saving(client):
    headers = ['模板名称', '分类', '提示词内容']
    bad = excel_file([headers, ['有效', '新分类', '内容'], ['无效', '', '   ']])
    response = client.post('/api/prompt-library/import', files={'file': ('test.xlsx', bad)})
    assert response.status_code == 422
    assert '第 3 行' in response.json()['detail']
    assert client.get('/api/prompt-templates').json()['items'] == []
    assert client.get('/api/prompt-categories').json()['items'] == []
    good = excel_file([headers, ['一', '新分类', '内容\n第二行'], ['二', '新分类', '内容二'], ['三', '', '无分类']])
    response = client.post('/api/prompt-library/import', files={'file': ('test.xlsx', good)})
    assert response.json() == {'imported': 3, 'created_categories': 1}
    assert len(client.get('/api/prompt-categories').json()['items']) == 1
    formula = excel_file([headers, ['公式', '', '=1+1']])
    assert client.post('/api/prompt-library/import', files={'file': ('test.xlsx', formula)}).status_code == 422
    assert client.post('/api/prompt-library/import', files={'file': ('bad.xlsx', b'bad')}).status_code == 422
    assert client.post('/api/prompt-library/import', files={'file': ('bad.xls', good)}).status_code == 422
    assert client.post('/api/prompt-library/import', files={'file': ('empty.xlsx', excel_file([headers]))}).status_code == 422


def test_excel_respects_user_scope(client):
    from backend.db.task_store import utc_now
    category = client.post('/api/prompt-categories', json={'name': '公共分类', 'visibility': 'public'}).json()
    client.post('/api/prompt-templates', json={'name': '公共', 'content': '公开内容', 'visibility': 'public', 'category_id': category['id']})
    client.post('/api/prompt-templates', json={'name': '管理员私有', 'content': '不应导出'})
    owner = 'test_excel_user'
    with client.app.state.store.transaction() as db:
        db.execute('INSERT INTO users (id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)', (owner, owner, 'unused', 'user', utc_now()))
    client.app.state.test_user = {'id': owner, 'role': 'user'}
    response = client.get('/api/prompt-library/export')
    book = load_workbook(io.BytesIO(response.content))
    assert list(book.active.values) == [('模板名称', '分类', '提示词内容'), ('公共', '公共分类', '公开内容')]
    book.close()
    assert client.post('/api/prompt-library/import', files={'file': ('test.xlsx', response.content)}).json() == {'imported': 1, 'created_categories': 1}
    items = client.get('/api/prompt-templates').json()['items']
    imported = next(item for item in items if item['owner_id'] == owner)
    assert imported['visibility'] == 'private'
    assert imported['category_id'] != category['id']


def test_excel_row_limit(client):
    headers = ['模板名称', '分类', '提示词内容']
    response = client.post('/api/prompt-library/import', files={'file': ('test.xlsx', excel_file([headers] + [['名称', '', '内容']] * 1001))})
    assert response.status_code == 422
    assert '1000' in response.json()['detail']
    assert client.get('/api/prompt-templates').json()['items'] == []
