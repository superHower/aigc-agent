from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


MAX_MASK_BYTES = 4 * 1024 * 1024


def validate_bbox(width: int, height: int, bbox: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = bbox
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("mask rectangle is outside image bounds")


def create_mask(
    width: int,
    height: int,
    bbox: tuple[int, int, int, int],
    path: Path,
) -> Path:
    validate_bbox(width, height, bbox)
    path.parent.mkdir(parents=True, exist_ok=True)
    mask = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    draw = ImageDraw.Draw(mask)
    draw.rectangle(bbox, fill=(255, 255, 255, 0))
    mask.save(path, format="PNG", optimize=True)
    if path.stat().st_size > MAX_MASK_BYTES:
        path.unlink(missing_ok=True)
        raise ValueError("generated mask exceeds the 4 MB limit")
    with Image.open(path) as saved:
        if saved.size != (width, height) or saved.mode != "RGBA":
            path.unlink(missing_ok=True)
            raise ValueError("generated mask has invalid dimensions or mode")
    return path

