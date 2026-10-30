import pytest
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
        request.state.user = {'id': owner, 'role': 'admin'}
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
