import asyncio
from pathlib import Path

from PIL import Image

from backend.db.task_store import TaskStore, utc_now
from backend.services.task_manager import TaskManager


class FakeEditor:
    def __init__(self, root: Path):
        self.root = root
        self.calls = []
        self.client = object()

    async def edit(self, **kwargs):
        self.calls.append(kwargs)
        output = self.root / "output" / f"{kwargs['job_id']}.png"
        output.parent.mkdir(exist_ok=True)
        with Image.open(kwargs["input_path"]) as source:
            source.save(output)
        return output, {}


def test_batch_jobs_are_serial_per_source_and_finalize(tmp_path: Path):
    source = tmp_path / "source.png"
    mask = tmp_path / "mask.png"
    Image.new("RGB", (20, 20), "white").save(source)
    Image.new("RGBA", (20, 20), (0, 0, 0, 255)).save(mask)
    store = TaskStore(tmp_path / "tasks.db")
    store.register_file(dict(id="src_1", original_name="source.png", path=str(source), mime_type="image/png", width=20, height=20, size=1, created_at=utc_now()))
    editor = FakeEditor(tmp_path)
    manager = TaskManager(store, editor, tmp_path, 2, 10, 0)
    jobs = [
        dict(id="j1", source_id="src_1", step="text_T1", target_id="T1", prompt="1", mask_path=str(mask), input_path=str(source)),
        dict(id="j2", source_id="src_1", step="text_T2", target_id="T2", prompt="2", mask_path=str(mask), input_path=str(source)),
    ]
    store.create_batch("task_1", ["src_1"], {"size": "auto", "quality": "high", "output_format": "png"}, jobs)
    async def run_batch():
        await manager.create_batch("task_1", {"src_1": jobs}, {"size": "auto", "quality": "high", "output_format": "png"})
        await manager.running_tasks["task_1"]

    asyncio.run(run_batch())
    task = store.get_task("task_1")
    assert task["status"] == "completed"
    stored_jobs = store.get_jobs("task_1")
    assert [job["status"] for job in stored_jobs] == ["done", "done"]
    assert editor.calls[1]["input_path"] == Path(stored_jobs[0]["output_path"])


def test_task_store_terminal_state_is_immutable(tmp_path: Path):
    store = TaskStore(tmp_path / "tasks.db")
    store.create_batch("task_1", [], {}, [])
    store.set_task_status("task_1", "completed")
    try:
        store.set_task_status("task_1", "running")
    except ValueError:
        pass
    else:
        raise AssertionError("terminal task state was changed")
