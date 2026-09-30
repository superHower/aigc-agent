from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageColor


class CompositeError(ValueError):
    pass


def compose_images(
    image_paths: list[Path],
    output_path: Path,
    *,
    width: int,
    gap: int,
    background_color: str,
    padding_top: int,
    padding_bottom: int,
) -> tuple[int, int]:
    if not image_paths:
        raise CompositeError("image_ids must contain at least one image")
    if not 1 <= width <= 10000:
        raise CompositeError("width must be between 1 and 10000")
    if not 0 <= gap <= 5000:
        raise CompositeError("gap must be between 0 and 5000")
    if not 0 <= padding_top <= 10000 or not 0 <= padding_bottom <= 10000:
        raise CompositeError("padding must be between 0 and 10000")
    try:
        background = ImageColor.getcolor(background_color, "RGBA")
    except ValueError as exc:
        raise CompositeError("background_color must be a valid CSS color") from exc

    resized: list[Image.Image] = []
    try:
        for path in image_paths:
            if not path.exists() or not path.is_file():
                raise CompositeError(f"image does not exist: {path.name}")
            with Image.open(path) as source:
                image = source.convert("RGBA")
                target_height = max(1, round(image.height * width / image.width))
                resized.append(image.resize((width, target_height), Image.Resampling.LANCZOS))
        total_height = padding_top + padding_bottom + sum(image.height for image in resized)
        total_height += gap * max(0, len(resized) - 1)
        canvas = Image.new("RGBA", (width, total_height), background)
        y = padding_top
        for image in resized:
            canvas.alpha_composite(image, (0, y))
            y += image.height + gap
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(output_path, "PNG", optimize=True)
        return width, total_height
    finally:
        for image in resized:
            image.close()
