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
            f"仅将背景替换为：{context.background}。"
            f"保持{context.subject}完全不变，包括形状、比例、颜色、材质、金属质感、线缆、接触阴影以及现有的所有文字和 Logo。"
            "保留原始构图、相机角度和产品位置。"
            f"不得修改{context.subject}的任何部分。输出一张写实的电商产品图片。"
        )
    if context.prompt_type is PromptType.SHADE:
        _required(context.color, "color")
        return (
            f"仅将{context.target}的颜色修改为：{context.color}。"
            f"保持其形状、材质纹理、接缝、缝线、框架、灯泡、线缆、背景以及所有文字和 Logo 完全不变。"
            "保留原始光照、阴影和透视关系。不得修改其他任何内容。输出一张写实的电商产品图片。"
        )
    if context.prompt_type is PromptType.BULB:
        _required(context.bulb, "bulb")
        return (
            f"仅将{context.target}替换为：{context.bulb}。"
            "匹配原始灯座位置、尺寸、透视关系和光照。"
            "保持周围产品、线缆、背景以及所有文字和 Logo 完全不变。不得修改其他任何内容。"
            "输出一张写实的电商产品图片。"
        )
    if context.prompt_type is PromptType.TEXT:
        _required(context.original, "original")
        _required(context.replace, "replace")
        _required(context.position, "position")
        return (
            f'将位于{_position_label(context.position)}区域的文字“{_quote(context.original)}”替换为“{_quote(context.replace)}”。'
            "严格匹配原文字体样式、字重、颜色、字号、透视关系和阴影。新文字必须拼写准确、对齐自然。"
            "不得修改其他文字、图形、产品或背景。输出一张写实的电商产品图片。"
        )
    if context.prompt_type is PromptType.LOGO:
        _required(context.brand, "brand")
        return (
            f"移除{_position_label(context.position)}区域的现有 Logo。"
            f"使用图片 2 中的 Logo，将其替换为 {_quote(context.brand)} 字标。"
            "将 Logo 缩放到相同边界框，保持原始宽高比，并保留该区域的背景纹理和光照。"
            "不得修改图片中的其他内容。输出一张写实的电商产品图片。"
        )
    raise ValueError(f"unsupported prompt type: {context.prompt_type}")


def _required(value: str, field: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field} is required")


def _position_label(position: str) -> str:
    labels = {
        "top-left": "左上",
        "top-center": "顶部居中",
        "top-right": "右上",
        "middle-left": "左侧居中",
        "center": "正中",
        "middle-right": "右侧居中",
        "bottom-left": "左下",
        "bottom-center": "底部居中",
        "bottom-right": "右下",
    }
    return labels.get(position, position)
