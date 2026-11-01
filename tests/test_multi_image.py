import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.db.task_store import TaskStore, utc_now
from backend.main import app
from backend.models.schemas import AnalyzeFileResult, MultiImageRequest, TextBlockView
from backend.services.multi_image import fit_output, plan_multi_image
from backend.services.task_manager import TaskManager


def make_sources(root: Path, count: int):
    root.mkdir(parents=True, exist_ok=True)
    sources = {}
    for index in range(1, count + 1):
        path = root / f"图{index}.png"
        Image.new("RGB", (40, 20), "red").save(path)
        sources[f"src_{index}"] = dict(id=f"src_{index}", original_name=path.name, path=str(path), mime_type="image/png", width=40, height=20, size=path.stat().st_size, created_at=utc_now())
    return sources


def test_fifty_images_four_ratios_sorted_and_unique(tmp_path):
    sources = make_sources(tmp_path, 50)
    payload = MultiImageRequest(source_ids=list(reversed(sources)), prompt="统一背景", aspect_ratios=["original", "1:1", "3:4", "16:9"])
    source_ids, jobs, chains, rule = plan_multi_image(payload, sources, {}, tmp_path)
    assert source_ids == list(sources)
    assert len(jobs) == 200
    assert all(len(chain) == 4 for chain in chains.values())
    assert len({options["filename"] for options in rule["outputs"].values()}) == 200
    assert rule["outputs"][jobs[0]["id"]]["filename"] == "图1-原比例.png"
    assert rule["outputs"][jobs[4]["id"]]["filename"] == "图2-原比例.png"
    assert all("禁止拉伸" not in job["prompt"] for job in jobs)


@pytest.mark.parametrize("mode", ["shared", "reference"])
@pytest.mark.parametrize("enabled", [False, True])
def test_natural_proportions_instruction_is_optional(tmp_path, mode, enabled):
    sources = make_sources(tmp_path, 2)
    instructions = "按要求重新设计产品布局"
    payload = MultiImageRequest(
        source_ids=["src_2"], mode=mode, reference_file_id="src_1" if mode == "reference" else None,
        prompt=instructions, aspect_ratios=["original", "1:1", "3:4", "16:9"],
        preserve_natural_proportions=enabled,
    )
    _, jobs, _, _ = plan_multi_image(payload, sources, {}, tmp_path)
    suffix = "必须保持主体、文字和其他内容的自然比例，禁止拉伸、挤压或变形。可调整布局、间距或扩展背景来适配画布，保留完整主体。"
    for job in jobs:
        assert instructions in job["prompt"]
        assert "输出画布比例为" in job["prompt"]
        assert (suffix in job["prompt"]) is enabled
        assert job["prompt"].count(suffix) == int(enabled)


def test_reference_mode_and_validation(tmp_path):
    sources = make_sources(tmp_path, 4)
    payload = MultiImageRequest(source_ids=["src_4", "src_2", "src_3"], mode="reference", reference_file_id="src_1", reference_component="背景")
    source_ids, jobs, _, rule = plan_multi_image(payload, sources, {}, tmp_path)
    assert source_ids == ["src_2", "src_3", "src_4"]
    assert len(jobs) == 3
    assert rule["reference_paths"] == [sources["src_1"]["path"]]
    assert all("其他内容不变" in job["prompt"] for job in jobs)
    with pytest.raises(ValueError, match="参考图片不能"):
        plan_multi_image(payload.model_copy(update={"source_ids": ["src_1"]}), sources, {}, tmp_path)
    with pytest.raises(ValueError, match="OCR"):
        plan_multi_image(payload.model_copy(update={"ocr_enabled": True}), sources, {}, tmp_path)
    with pytest.raises(ValueError, match="OCR"):
        plan_multi_image(MultiImageRequest(source_ids=["src_1"], prompt="背景", ocr_enabled=True), sources, {}, tmp_path)


def test_reference_full_instructions_preserved_for_each_target_and_ratio(tmp_path):
    sources = make_sources(tmp_path, 3)
    instructions = "将背景换成参考图中的场景。\n调整产品位置和阴影，保留文字，不要增加其他物品。" + "保留细节。" * 250
    payload = MultiImageRequest(
        source_ids=["src_3", "src_2"], mode="reference", reference_file_id="src_1",
        prompt=instructions, reference_component="背景", aspect_ratios=["original", "1:1"],
    )
    _, jobs, _, rule = plan_multi_image(payload, sources, {}, tmp_path)
    assert len(jobs) == 4
    assert rule["reference_paths"] == [sources["src_1"]["path"]]
    for job in jobs:
        assert "第一张输入图是当前待处理图片，第二张输入图是参考图" in job["prompt"]
        assert f"请根据以下用户要求编辑第一张图片：\n{instructions}\n输出画布比例" in job["prompt"]
        assert "用户未提及的部分默认尽量保留" in job["prompt"]
        assert "其他内容不变" not in job["prompt"]
        assert "【" not in job["prompt"]
        assert job["input_path"] == sources[job["source_id"]]["path"]


def test_reference_requires_instructions(tmp_path):
    sources = make_sources(tmp_path, 2)
    payload = MultiImageRequest(
        source_ids=["src_2"], mode="reference", reference_file_id="src_1", prompt="  \n",
    )
    with pytest.raises(ValueError, match="请填写编辑要求"):
        plan_multi_image(payload, sources, {}, tmp_path)


def test_fit_output_does_not_stretch(tmp_path):
    path = tmp_path / "result.png"
    Image.new("RGB", (100, 50), "red").save(path)
    fit_output(path, 100, 100)
    with Image.open(path) as image:
        assert image.size == (100, 100)
        assert image.getpixel((50, 0)) == (255, 255, 255)
        assert image.getpixel((50, 25)) == (255, 0, 0)
        assert image.getpixel((50, 74)) == (255, 0, 0)
        assert image.getpixel((50, 75)) == (255, 255, 255)


def test_prompt_group_independent_outputs_and_snapshot(tmp_path):
    sources = make_sources(tmp_path, 1)
    group = {'id': 'group', 'name': '套图', 'templates': [
        {'id': 'a', 'name': '白底', 'content': '换成白色背景'},
        {'id': 'b', 'name': '客厅', 'content': '放在客厅里'},
    ]}
    payload = MultiImageRequest(source_ids=['src_1'], mode='prompt_group', prompt_group_id='group')
    ids, jobs, chains, rule = plan_multi_image(payload, sources, {}, tmp_path, group)
    assert len(jobs) == 2
    assert [job['target_id'] for job in jobs] == ['a', 'b']
    assert '换成白色背景' in jobs[0]['prompt'] and '放在客厅里' not in jobs[0]['prompt']
    assert '放在客厅里' in jobs[1]['prompt'] and '换成白色背景' not in jobs[1]['prompt']
    assert all(options['variant'] for options in rule['outputs'].values())
    assert len({options['filename'] for options in rule['outputs'].values()}) == 2
    store = TaskStore(tmp_path / 'group.db')
    store.create_batch('group_task', ids, rule, jobs)
    editor = ConcurrentEditor(tmp_path)
    manager = TaskManager(store, editor, tmp_path, 2, 10, 0, max_concurrency=2)

    async def run():
        await manager.create_batch('group_task', chains, rule)
        await manager.running_tasks['group_task']

    asyncio.run(run())
    assert len(editor.calls) == 2
    assert all(call['input_path'] == Path(sources['src_1']['path']) for call in editor.calls)
    assert store.get_task('group_task')['status'] == 'completed'
    import json
    group['templates'][0]['content'] = '已修改'
    assert json.loads(store.get_task('group_task')['edit_rule'])['prompt_group']['templates'][0]['content'] == '换成白色背景'
    for update in [{'source_ids': ['src_1', 'src_2']}, {'aspect_ratios': ['1:1']}, {'ocr_enabled': True}, {'prompt_group_id': None}]:
        with pytest.raises(ValueError):
            plan_multi_image(payload.model_copy(update=update), sources, {}, tmp_path, group)


class ConcurrentEditor:
    def __init__(self, root):
        self.root = root
        self.active = 0
        self.peak = 0
        self.calls = []
        self.fail_job = None

    async def edit(self, **kwargs):
        self.calls.append(kwargs)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.015)
            if kwargs["job_id"] == self.fail_job:
                raise RuntimeError("simulated failure")
            path = self.root / f"{kwargs['job_id']}.png"
            with Image.open(kwargs["input_path"]) as image:
                image.save(path)
            return path, {}
        finally:
            self.active -= 1


def test_multiple_tasks_global_limit_failure_isolation_and_retry(tmp_path):
    sources = make_sources(tmp_path, 4)
    store = TaskStore(tmp_path / "tasks.db")
    editor = ConcurrentEditor(tmp_path)
    manager = TaskManager(store, editor, tmp_path, 2, 10, 0, max_concurrency=2)
    plans = []
    for index in range(2):
        source_ids, jobs, chains, rule = plan_multi_image(MultiImageRequest(source_ids=[f"src_{index + 1}"], prompt="背景", aspect_ratios=["original", "1:1"]), sources, {}, tmp_path)
        store.create_batch(f"task_{index}", source_ids, rule, jobs)
        plans.append((jobs, chains, rule))
    editor.fail_job = plans[0][0][0]["id"]

    async def run():
        for index, (_, chains, rule) in enumerate(plans):
            await manager.create_batch(f"task_{index}", chains, rule)
        await asyncio.gather(*list(manager.running_tasks.values()))
        assert store.get_task("task_0")["status"] == "partial_failed"
        assert store.get_task("task_1")["status"] == "completed"
        assert editor.peak == 2
        assert len(editor.calls) == 4
        editor.fail_job = None
        await manager.retry("task_0")
        await manager.running_tasks["task_0"]
        assert len(editor.calls) == 5
        assert store.get_task("task_0")["status"] == "completed"

    asyncio.run(run())
    for call in editor.calls:
        source_id = store.get_job(call["job_id"])["source_id"]
        assert call["input_path"] == Path(sources[source_id]["path"])


def test_cancel_queued_jobs_before_model_call(tmp_path):
    sources = make_sources(tmp_path, 1)
    store = TaskStore(tmp_path / "tasks.db")
    editor = ConcurrentEditor(tmp_path)
    manager = TaskManager(store, editor, tmp_path, 2, 10, 0, max_concurrency=1)
    source_ids, jobs, chains, rule = plan_multi_image(MultiImageRequest(source_ids=["src_1"], prompt="背景", aspect_ratios=["original", "1:1", "3:4"]), sources, {}, tmp_path)
    store.create_batch("task_cancel", source_ids, rule, jobs)

    async def run():
        await manager.api_semaphore.acquire()
        await manager.create_batch("task_cancel", chains, rule)
        await asyncio.sleep(0.01)
        manager.cancel("task_cancel")
        manager.api_semaphore.release()
        await manager.running_tasks["task_cancel"]
    asyncio.run(run())
    assert editor.calls == []
    assert all(job["status"] == "cancelled" for job in store.get_jobs("task_cancel"))


def test_resume_active_tasks_after_restart(tmp_path):
    sources = make_sources(tmp_path, 1)
    store = TaskStore(tmp_path / "tasks.db")
    source_ids, jobs, chains, rule = plan_multi_image(MultiImageRequest(source_ids=["src_1"], prompt="背景", aspect_ratios=["original", "1:1"]), sources, {}, tmp_path)
    store.create_batch("task_resume", source_ids, rule, jobs)
    store.update_job(jobs[0]["id"], status="done", output_path=jobs[0]["input_path"])
    store.update_job(jobs[1]["id"], status="processing")
    store.set_task_status("task_resume", "running")
    store.recover_processing()
    editor = ConcurrentEditor(tmp_path)
    manager = TaskManager(store, editor, tmp_path, 2, 10, 0, max_concurrency=2)

    async def run():
        await manager.resume_active_tasks()
        await manager.running_tasks["task_resume"]

    asyncio.run(run())
    assert store.get_task("task_resume")["status"] == "completed"
    assert store.get_job(jobs[0]["id"])["status"] == "done"
    assert store.get_job(jobs[1]["id"])["status"] == "done"
    assert len(editor.calls) == 1


def test_ocr_then_independent_variants_and_retry_preserves_input(tmp_path):
    sources = make_sources(tmp_path, 1)
    analysis = AnalyzeFileResult(file_id="src_1", width=40, height=20, text_blocks=[TextBlockView(id="T1", bbox=(0, 0, 20, 10), position="top-left", original="旧文案", mask_url="/api/files/mask_1")])
    payload = MultiImageRequest(source_ids=["src_1"], prompt="背景", ocr_enabled=True, aspect_ratios=["original", "1:1"], per_source_overrides={"src_1": {"text_blocks": [{"id": "T1", "replace": "新文案"}]}})
    source_ids, jobs, chains, rule = plan_multi_image(payload, sources, {"src_1": analysis}, tmp_path)
    assert len(jobs) == 3
    store = TaskStore(tmp_path / "tasks.db")
    store.create_batch("task_ocr", source_ids, rule, jobs)
    editor = ConcurrentEditor(tmp_path)
    editor.fail_job = jobs[1]["id"]
    manager = TaskManager(store, editor, tmp_path, 2, 10, 0, max_concurrency=2)

    async def run():
        await manager.create_batch("task_ocr", chains, rule)
        await manager.running_tasks["task_ocr"]
        assert store.get_task("task_ocr")["status"] == "partial_failed"
        text_output = Path(store.get_job(jobs[0]["id"])["output_path"])
        assert all(call["input_path"] == text_output for call in editor.calls[1:])
        editor.fail_job = None
        await manager.retry("task_ocr", jobs[1]["id"])
        await manager.running_tasks["task_ocr"]
        assert len(editor.calls) == 4
        assert editor.calls[-1]["input_path"] == text_output
        assert store.get_task("task_ocr")["status"] == "completed"

    asyncio.run(run())


def test_api_without_ocr_and_zip_order(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    sources = make_sources(tmp_path, 3)
    for source in sources.values():
        store.register_file(source)

    class FakeManager:
        async def create_batch(self, task_id, chains, rule):
            for chain in chains.values():
                for job in chain:
                    store.update_job(job["id"], status="done", output_path=job["input_path"])
            store.finalize_task(task_id)

    monkeypatch.setattr(app.state, "store", store, raising=False)
    monkeypatch.setattr(app.state, "manager", FakeManager(), raising=False)
    monkeypatch.setattr(app.state, "settings", SimpleNamespace(data_dir=tmp_path, max_concurrency=10), raising=False)
    client = TestClient(app)
    from backend.db.operations import bootstrap_admin
    bootstrap_admin(store, 'admin', 'test-password-123')
    assert client.post('/api/auth/login', json={'account': 'admin', 'password': 'test-password-123'}).status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['csrf']
    response = client.post("/api/generate/multi-image", json={"source_ids": ["src_3", "src_1", "src_2"], "prompt": "统一背景"})
    assert response.status_code == 200
    assert response.json()["estimated_cost"] == 0.15
    task_id = response.json()["task_id"]
    detail = client.get(f"/api/task/{task_id}").json()
    assert detail["max_concurrency"] == 10
    assert detail["mode"] == "shared"
    assert detail["jobs"][0]["output_filename"] == "图1-原比例.png"
    assert detail["jobs"][0]["source_filename"] == "图1.png"
    assert all(job["reference_urls"] == [] for job in detail["jobs"])
    response = client.get(f"/api/task/{task_id}/download")
    assert response.status_code == 200
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["图1-原比例.png", "图2-原比例.png", "图3-原比例.png"]
    assert client.post("/api/generate/multi-image", json={"source_ids": ["src_1"], "prompt": "背景", "ocr_enabled": True}).status_code == 422
    assert client.get("/api/task/unknown/download").status_code == 404
    response = client.post("/api/generate/multi-image", json={
        "source_ids": ["src_2", "src_3"], "mode": "reference",
        "reference_file_id": "src_1", "prompt": "参考背景，保留产品文字",
    })
    assert response.status_code == 200
    reference_detail = client.get(f"/api/task/{response.json()['task_id']}").json()
    assert reference_detail["mode"] == "reference"
    assert all(job["reference_urls"] == ["/api/files/src_1"] for job in reference_detail["jobs"])
    assert client.get(reference_detail["jobs"][0]["reference_urls"][0]).status_code == 200
    assert {job["source_id"] for job in reference_detail["jobs"]} == {"src_2", "src_3"}
    for job in reference_detail["jobs"]:
        assert job["source_filename"] == sources[job["source_id"]]["original_name"]
        assert job["prompt"] == store.get_job(job["id"])["prompt"]
        assert "参考背景，保留产品文字" in job["prompt"]
        assert "第一张输入图是当前待处理图片" in job["prompt"]
        assert "输出画布比例为 40:20" in job["prompt"]

    # Older multi-image tasks have no explicit mode; infer it from saved references.
    import json
    for recorded_task, expected in [(detail, "shared"), (reference_detail, "reference")]:
        saved_rule = json.loads(store.get_task(recorded_task["id"])["edit_rule"])
        assert saved_rule.pop("mode") == expected
        with store.transaction() as db:
            db.execute("UPDATE tasks SET edit_rule=? WHERE id=?", (json.dumps(saved_rule), recorded_task["id"]))
        assert client.get(f"/api/task/{recorded_task['id']}").json()["mode"] == expected
    listed = {task["id"]: task["mode"] for task in client.get("/api/tasks").json()["items"]}
    assert listed[detail["id"]] == "shared"
    assert listed[reference_detail["id"]] == "reference"
