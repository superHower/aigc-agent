from __future__ import annotations

import hashlib
import io
import secrets
from pathlib import Path

import magic
from PIL import Image


ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_SOURCE_BYTES = 50 * 1024 * 1024
MIME_BY_FORMAT = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}


def safe_extension(filename: str, image_format: str) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(
            image_format, ".png"
        )
    return extension


def validate_image_bytes(data: bytes, filename: str) -> tuple[Image.Image, str]:
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("image exceeds the 50 MB limit")
    detected_mime = magic.from_buffer(data, mime=True)
    if detected_mime not in set(MIME_BY_FORMAT.values()):
        raise ValueError("uploaded file has an unsupported file signature")
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise ValueError("uploaded file is not a valid image") from exc
    image_format = (image.format or "").upper()
    mime_type = MIME_BY_FORMAT.get(image_format)
    if mime_type is None:
        raise ValueError("unsupported image format")
    extension = Path(filename).suffix.lower()
    if extension and extension not in ALLOWED_EXTENSIONS:
        raise ValueError("unsupported image extension")
    return image, mime_type


def save_source(data: bytes, filename: str, image: Image.Image, root: Path) -> Path:
    directory = root / "source"
    directory.mkdir(parents=True, exist_ok=True)
    extension = safe_extension(filename, (image.format or "PNG").upper())
    digest = hashlib.sha256(data).hexdigest()[:24]
    path = (directory / f"{digest}_{secrets.token_hex(8)}{extension}").resolve()
    root_resolved = root.resolve()
    if root_resolved not in path.parents:
        raise ValueError("invalid storage path")
    path.write_bytes(data)
    return path
