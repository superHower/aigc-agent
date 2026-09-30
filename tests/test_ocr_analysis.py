from pathlib import Path

import numpy as np
from PIL import Image

from backend.db.task_store import TaskStore, utc_now
from backend.services.analyzer import Analyzer, bbox_to_position
from backend.services.ocr_service import OCRService, OCRText


def test_legacy_and_modern_results():
    service = OCRService()
    polygon = [[10, 20], [100, 20], [100, 40], [10, 40]]
    legacy = [[[polygon, ("新品首发", 0.95)]]]
    modern = [{"rec_texts": ["新品首发"], "rec_polys": np.array([polygon]), "rec_scores": np.array([0.95])}]
    assert service._parse(legacy) == service._parse(modern)
    assert service._parse(legacy)[0].bbox == (10, 20, 100, 40)


def test_positions():
    assert bbox_to_position((0, 0, 20, 20), 100, 100) == "top-left"
    assert bbox_to_position((40, 40, 60, 60), 100, 100) == "center"


def test_analysis_masks_cache_and_unknown_file(tmp_path: Path):
    source = tmp_path / "source" / "source.png"
    source.parent.mkdir()
    Image.new("RGB", (100, 100)).save(source)
    store = TaskStore(tmp_path / "tasks.db")
    store.register_file(dict(id="src_1", original_name="source.png", path=str(source), mime_type="image/png", width=100, height=100, size=source.stat().st_size, created_at=utc_now()))

    class FakeOCR:
        calls = 0

        def detect(self, path):
            self.calls += 1
            return [OCRText((60, 70, 95, 90), "第二块", 0.9), OCRText((1, 1, 30, 20), "第一块", 0.95)]

    ocr = FakeOCR()
    analyzer = Analyzer(store, tmp_path, ocr)
    result = analyzer.analyze("src_1")
    assert result.error is None
    assert [block.id for block in result.text_blocks] == ["T1", "T2"]
    assert result.text_blocks[0].original == "第一块"
    for block in result.text_blocks:
        record = store.get_file(block.mask_url.rsplit("/", 1)[1])
        with Image.open(record["path"]) as mask:
            assert mask.mode == "RGBA"
            assert mask.size == (100, 100)
    assert analyzer.analyze("src_1") == result
    assert ocr.calls == 1
    assert analyzer.analyze("missing").error == "file_not_found"


def test_failed_file_does_not_cache_error(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (20, 20)).save(source)
    store = TaskStore(tmp_path / "tasks.db")
    store.register_file(dict(id="src_1", original_name="source.png", path=str(source), mime_type="image/png", width=20, height=20, size=source.stat().st_size, created_at=utc_now()))

    class BrokenOCR:
        def detect(self, path):
            raise RuntimeError("unavailable")

    result = Analyzer(store, tmp_path, BrokenOCR()).analyze("src_1")
    assert "unavailable" in result.error
    assert store.get_analysis("src_1") is None
