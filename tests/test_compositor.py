from pathlib import Path

import pytest
from PIL import Image

from backend.services.compositor import CompositeError, compose_images


def test_compose_preserves_order_and_calculates_canvas(tmp_path: Path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (100, 50), "red").save(first)
    Image.new("RGB", (50, 100), "blue").save(second)
    output = tmp_path / "nested" / "composite.png"
    width, height = compose_images([first, second], output, width=200, gap=10, background_color="#00FF00", padding_top=5, padding_bottom=7)
    assert (width, height) == (200, 522)
    with Image.open(output) as image:
        assert image.size == (200, 522)
        assert image.getpixel((0, 0))[:3] == (0, 255, 0)
        assert image.getpixel((100, 5))[:3] == (255, 0, 0)
        assert image.getpixel((100, 115))[:3] == (0, 0, 255)


def test_compose_rejects_invalid_options(tmp_path: Path):
    image = tmp_path / "image.png"
    Image.new("RGB", (10, 10), "white").save(image)
    with pytest.raises(CompositeError, match="valid CSS color"):
        compose_images([image], tmp_path / "output.png", width=100, gap=0, background_color="not-a-color", padding_top=0, padding_bottom=0)
