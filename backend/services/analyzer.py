from pathlib import Path
from threading import Lock
from uuid import uuid4

from PIL import Image

from backend.db.task_store import TaskStore, utc_now
from backend.models.schemas import AnalyzeFileResult, TextBlockView
from backend.services.mask_generator import create_mask
from backend.services.ocr_service import OCRService


def bbox_to_position(bbox: tuple[int, int, int, int], width: int, height: int) -> str:
    x1, y1, x2, y2 = bbox
    center_x = (x1 + x2) / (2 * width)
    center_y = (y1 + y2) / (2 * height)
    column = "left" if center_x < 1 / 3 else "right" if center_x > 2 / 3 else "center"
    row = "top" if center_y < 1 / 3 else "bottom" if center_y > 2 / 3 else "middle"
    return "center" if (row, column) == ("middle", "center") else f"{row}-{column}"


class Analyzer:
    def __init__(self, store: TaskStore, data_dir: Path, ocr: OCRService) -> None:
        self.store = store
        self.data_dir = data_dir
        self.ocr = ocr
        self.lock = Lock()

    def analyze(self, file_id: str) -> AnalyzeFileResult:
        with self.lock:
            source = self.store.get_file(file_id)
            if source is None:
                return AnalyzeFileResult(file_id=file_id, width=0, height=0, error="file_not_found")
            cached = self.store.get_analysis(file_id)
            if cached is not None:
                return AnalyzeFileResult.model_validate_json(cached)
            width, height = source["width"], source["height"]
            generated: list[Path] = []
            try:
                detections = sorted(self.ocr.detect(Path(source["path"])), key=lambda item: (item.bbox[1], item.bbox[0], item.text))
                blocks = []
                records = []
                for detection in detections:
                    x1, y1, x2, y2 = detection.bbox
                    bbox = (max(0, x1), max(0, y1), min(width, x2), min(height, y2))
                    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                        continue
                    block_id = f"T{len(blocks) + 1}"
                    mask_id = f"mask_{uuid4().hex}"
                    mask_path = self.data_dir / "masks" / f"{mask_id}.png"
                    padded = (max(0, bbox[0] - 6), max(0, bbox[1] - 6), min(width, bbox[2] + 6), min(height, bbox[3] + 6))
                    create_mask(width, height, padded, mask_path)
                    generated.append(mask_path)
                    records.append(dict(id=mask_id, original_name=f"{block_id}.png", path=str(mask_path), mime_type="image/png", width=width, height=height, size=mask_path.stat().st_size, created_at=utc_now()))
                    blocks.append(TextBlockView(id=block_id, bbox=bbox, position=bbox_to_position(bbox, width, height), original=detection.text, confidence=detection.confidence, mask_url=f"/api/files/{mask_id}"))
                thumbnail_id = f"thumb_{uuid4().hex}"
                thumbnail_path = self.data_dir / "source" / f"{thumbnail_id}.png"
                with Image.open(source["path"]) as image:
                    image.thumbnail((400, 400))
                    image.save(thumbnail_path, format="PNG")
                    records.append(dict(id=thumbnail_id, original_name="thumbnail.png", path=str(thumbnail_path), mime_type="image/png", width=image.width, height=image.height, size=thumbnail_path.stat().st_size, created_at=utc_now()))
                generated.append(thumbnail_path)
                result = AnalyzeFileResult(file_id=file_id, width=width, height=height, text_blocks=blocks, thumbnail_url=f"/api/files/{thumbnail_id}")
                self.store.save_analysis(file_id, result.model_dump_json(), records)
                return result
            except Exception as exc:
                for path in generated:
                    path.unlink(missing_ok=True)
                return AnalyzeFileResult(file_id=file_id, width=width, height=height, error=f"ocr_analysis_failed: {exc}")
