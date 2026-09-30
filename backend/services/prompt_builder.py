from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PromptType(StrEnum):
    BACKGROUND = "background"
    SHADE = "shade"
    BULB = "bulb"
    TEXT = "text"
    LOGO = "logo"


@dataclass(frozen=True)
class PromptContext:
    prompt_type: PromptType
    background: str = ""
    subject: str = "product"
    target: str = "target component"
    color: str = ""
    bulb: str = ""
    original: str = ""
    replace: str = ""
    position: str = "center"
    brand: str = ""


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').strip()


def build_prompt(context: PromptContext) -> str:
    if context.prompt_type is PromptType.BACKGROUND:
        _required(context.background, "background")
        return (
            f"Replace only the background with {context.background}. "
            f"Keep the {context.subject} completely unchanged — its shape, proportions, color, "
            "material, metal finish, cable, contact shadows, and all existing text and logo. "
            "Preserve the original composition, camera angle, and product position. "
            f"Do not alter any part of the {context.subject}. "
            "Output a photorealistic e-commerce product image."
        )
    if context.prompt_type is PromptType.SHADE:
        _required(context.color, "color")
        return (
            f"Change only the {context.target} color to {context.color}. "
            f"Keep its shape, material texture, seams, stitching, frame, bulb, cable, "
            "background, and all text and logo exactly the same. "
            "Preserve the original lighting, shadows, and perspective. "
            "Do not alter anything else. Output a photorealistic product image."
        )
    if context.prompt_type is PromptType.BULB:
        _required(context.bulb, "bulb")
        return (
            f"Replace only the {context.target} with {context.bulb}. "
            "Match the original socket position, scale, perspective, and lighting. "
            "Keep the surrounding product, cable, background, and all text and logo "
            "completely unchanged. Do not alter anything else. "
            "Output a photorealistic product image."
        )
    if context.prompt_type is PromptType.TEXT:
        _required(context.original, "original")
        _required(context.replace, "replace")
        _required(context.position, "position")
        return (
            f'Replace the text "{_quote(context.original)}" located in the {context.position} area '
            f'with "{_quote(context.replace)}". Match the original font style, weight, color, size, '
            "perspective, and shadow exactly. The new text must be perfectly spelled and aligned. "
            "Do not alter any other text, graphics, product, or background. "
            "Output a photorealistic e-commerce product image."
        )
    if context.prompt_type is PromptType.LOGO:
        _required(context.brand, "brand")
        return (
            f"Remove the existing logo in the {context.position} area. "
            f"Replace it with the logo from Image 2: the {_quote(context.brand)} wordmark. "
            "Scale it to fit the same bounding box, maintain its original aspect ratio, "
            "and preserve the background texture and lighting in that area. "
            "Do not change anything else in the image. "
            "Output a photorealistic e-commerce product image."
        )
    raise ValueError(f"unsupported prompt type: {context.prompt_type}")


def _required(value: str, field: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field} is required")
