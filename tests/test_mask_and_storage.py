from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from backend.services.file_storage import validate_image_bytes
from backend.services.mask_generator import create_mask


def test_mask_marks_only_rectangle_as_transparent(tmp_path: Path) -> None:
    path = tmp_path / "mask.png"
    create_mask(20, 10, (2, 3, 8, 7), path)

    with Image.open(path) as mask:
        assert mask.mode == "RGBA"
        assert mask.size == (20, 10)
        assert mask.getpixel((0, 0))[3] == 255
        assert mask.getpixel((4, 5))[3] == 0


def test_mask_rejects_out_of_bounds_rectangle(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside image bounds"):
        create_mask(20, 10, (2, 3, 21, 7), tmp_path / "mask.png")


def test_image_validation_uses_real_format() -> None:
    image = Image.new("RGB", (2, 2), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    decoded, mime = validate_image_bytes(buffer.getvalue(), "photo.png")
    assert decoded.size == (2, 2)
    assert mime == "image/png"
