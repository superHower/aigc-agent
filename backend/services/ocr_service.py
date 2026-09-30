from __future__ import annotations

import logging
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OCRText:
    bbox: tuple[int, int, int, int]
    text: str
    confidence: float | None = None


class OCRService:
    def __init__(self) -> None:
        self._engine: Any | None = None
        self._api: str | None = None

    def _load_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "PaddleOCR is not installed. Install paddleocr and a compatible paddlepaddle runtime."
            ) from exc

        try:
            self._engine = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                lang="ch",
            )
            self._api = "predict"
        except (TypeError, ValueError) as new_api_error:
            logger.warning("PaddleOCR new API unavailable, trying legacy API: %s", new_api_error)
            try:
                self._engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
                self._api = "ocr"
            except Exception as legacy_error:
                raise RuntimeError(f"failed to initialize PaddleOCR: {legacy_error}") from legacy_error
        return self._engine

    def detect(self, image_path: Path) -> list[OCRText]:
        engine = self._load_engine()
        if self._api == "predict":
            raw = engine.predict(str(image_path))
        else:
            raw = engine.ocr(str(image_path), cls=True)
        return self._parse(raw)

    def _parse(self, raw: Any) -> list[OCRText]:
        entries: list[OCRText] = []
        self._collect(raw, entries)
        deduplicated: dict[tuple[tuple[int, int, int, int], str], OCRText] = {}
        for entry in entries:
            if entry.text.strip() and entry.bbox[2] > entry.bbox[0] and entry.bbox[3] > entry.bbox[1]:
                deduplicated[(entry.bbox, entry.text)] = entry
        return list(deduplicated.values())

    def _collect(self, value: Any, output: list[OCRText]) -> None:
        if value is None:
            return
        if isinstance(value, (list, tuple)):
            if self._looks_like_legacy_line(value):
                parsed = self._parse_legacy_line(value)
                if parsed:
                    output.append(parsed)
                    return
            for item in value:
                self._collect(item, output)
            return
        if isinstance(value, dict):
            for key in ("rec_texts", "texts"):
                texts = value.get(key)
                boxes = next((value[name] for name in ("rec_polys", "rec_boxes", "dt_polys", "boxes") if value.get(name) is not None), None)
                scores = value.get("rec_scores", value.get("scores"))
                if texts is not None and boxes is not None:
                    for index, text in enumerate(texts):
                        box = boxes[index] if index < len(boxes) else None
                        if box is not None:
                            output.append(self._from_box(box, str(text), self._score_at(scores, index)))
                    return
            for key in ("result", "res", "ocr_result", "data"):
                if key in value:
                    self._collect(value[key], output)
            return
        if isinstance(value, str):
            self._collect(json.loads(value), output)
            return
        for attribute in ("json", "res"):
            candidate = getattr(value, attribute, None)
            if callable(candidate):
                try:
                    self._collect(candidate(), output)
                except Exception:
                    pass
            elif candidate is not None:
                self._collect(candidate, output)
        for attribute in ("rec_texts", "texts"):
            texts = getattr(value, attribute, None)
            boxes = getattr(value, "rec_boxes", None)
            if boxes is None:
                boxes = getattr(value, "dt_polys", None)
            if texts is not None and boxes is not None:
                scores = getattr(value, "rec_scores", None)
                for index, text in enumerate(texts):
                    if index < len(boxes):
                        output.append(self._from_box(boxes[index], str(text), self._score_at(scores, index)))

    @staticmethod
    def _looks_like_legacy_line(value: list[Any]) -> bool:
        return len(value) == 2 and isinstance(value[1], (list, tuple)) and len(value[1]) >= 1 and isinstance(value[1][0], str)

    def _parse_legacy_line(self, value: list[Any]) -> OCRText | None:
        polygon = value[0]
        payload = value[1]
        if not isinstance(payload, (list, tuple)) or not payload:
            return None
        text = str(payload[0])
        confidence = float(payload[1]) if len(payload) > 1 and isinstance(payload[1], (int, float)) else None
        return self._from_box(polygon, text, confidence)

    @staticmethod
    def _score_at(scores: Any, index: int) -> float | None:
        if scores is not None and index < len(scores):
            try:
                return float(scores[index])
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _from_box(box: Any, text: str, confidence: float | None) -> OCRText:
        points = list(box)
        if len(points) == 4 and all(not hasattr(point, "__len__") for point in points):
            x1, y1, x2, y2 = points
        else:
            coordinates = [(float(point[0]), float(point[1])) for point in points]
            x1 = min(point[0] for point in coordinates)
            y1 = min(point[1] for point in coordinates)
            x2 = max(point[0] for point in coordinates)
            y2 = max(point[1] for point in coordinates)
        return OCRText((math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2)), text, confidence)
