from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps

from backend.models.schemas import AnalyzeFileResult, MultiImageRequest
from backend.services.mask_generator import create_mask
from backend.services.prompt_builder import PromptContext, PromptType, build_prompt


RATIO_LABELS = {"original": "原比例", "1:1": "1比1", "3:4": "3比4", "16:9": "16比9"}
RATIO_SIZES = {"1:1": (1024, 1024), "3:4": (900, 1200), "16:9": (1600, 900)}


def natural_key(name: str) -> list[tuple[int, object]]:
    return [(1, int(part)) if part.isdigit() else (0, part.casefold()) for part in re.split(r"(\d+)", name)]


def safe_stem(name: str) -> str:
    basename = name.replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(basename).stem).strip(" .")[:100] or "图片"


def plan_multi_image(payload: MultiImageRequest, sources: dict, analyses: dict[str, AnalyzeFileResult], data_dir: Path):
    if payload.mode == "shared" and not payload.prompt.strip():
        raise ValueError("请填写通用提示词")
    if payload.mode == "reference":
        if not payload.reference_file_id or payload.reference_file_id not in sources:
            raise ValueError("请选择有效的参考图片")
        if payload.reference_file_id in payload.source_ids:
            raise ValueError("参考图片不能同时作为待处理图片")
        if payload.ocr_enabled:
            raise ValueError("参考图组合模式不启用 OCR")
        if not payload.prompt.strip() and not payload.reference_component.strip():
            raise ValueError("请填写编辑要求")
    source_ids = sorted(payload.source_ids, key=lambda source_id: natural_key(sources[source_id]["original_name"]))
    rule = {"size": "auto", "quality": payload.quality, "output_format": "png", "multi_image": True,
            "reference_paths": [sources[payload.reference_file_id]["path"]] if payload.mode == "reference" else [], "outputs": {}}
    jobs = []
    source_jobs = {}
    used_names = set()
    for source_id in source_ids:
        source = sources[source_id]
        chain = []
        if payload.ocr_enabled:
            analysis = analyses.get(source_id)
            if analysis is None or analysis.error:
                raise ValueError(f"请先完成图片 OCR 识别：{source['original_name']}")
            blocks = {block.id: block for block in analysis.text_blocks}
            overrides = payload.per_source_overrides.get(source_id)
            for replacement in overrides.text_blocks if overrides else []:
                if not replacement.enabled or not replacement.replace.strip():
                    continue
                block = blocks.get(replacement.id)
                if block is None:
                    raise ValueError(f"未知文字块：{replacement.id}")
                if block.original.strip() == replacement.replace.strip():
                    continue
                mask_id = block.mask_url.rsplit("/", 1)[-1]
                mask_path = data_dir / "masks" / f"multi_{uuid4().hex}.png"
                create_mask(source["width"], source["height"], block.bbox, mask_path)
                job_id = f"multi_{uuid4().hex}"
                chain.append({"id": job_id, "source_id": source_id, "step": f"text_{block.id}", "target_id": mask_id,
                              "prompt": build_prompt(PromptContext(prompt_type=PromptType.TEXT, original=block.original, replace=replacement.replace, position=block.position)),
                              "input_path": source["path"], "mask_path": str(mask_path)})
                rule["outputs"][job_id] = {"filename": f"{safe_stem(source['original_name'])}-文字{block.id}.png"}
        full_mask = data_dir / "masks" / f"multi_{uuid4().hex}.png"
        create_mask(source["width"], source["height"], (0, 0, source["width"], source["height"]), full_mask)
        for ratio in payload.aspect_ratios:
            width, height = (source["width"], source["height"]) if ratio == "original" else RATIO_SIZES[ratio]
            prompt = payload.prompt.strip()
            if payload.mode == "reference":
                # Keep supporting replacement-only requests from older clients.
                instructions = prompt or f"请把第一张图的【{payload.reference_component.strip()}】替换为第二张图的对应内容，其他内容不变。"
                prompt = (
                    "第一张输入图是当前待处理图片，第二张输入图是参考图。"
                    "用户未提及的部分默认尽量保留；用户明确要求修改的部分按用户要求执行。"
                    f"\n请根据以下用户要求编辑第一张图片：\n{instructions}"
                )
            prompt += f"\n输出画布比例为 {width}:{height}。必须保持主体、文字和其他内容的自然比例，禁止拉伸、挤压或变形。可调整布局、间距或扩展背景来适配画布，保留完整主体。"
            job_id = f"multi_{uuid4().hex}"
            base = f"{safe_stem(source['original_name'])}-{RATIO_LABELS[ratio]}"
            filename = f"{base}.png"
            suffix = 2
            while filename.casefold() in used_names:
                filename = f"{base}-{suffix}.png"
                suffix += 1
            used_names.add(filename.casefold())
            rule["outputs"][job_id] = {"filename": filename, "width": width, "height": height, "variant": True,
                                       "size": "1024x1024" if width == height else "1536x1024" if width > height else "1024x1536"}
            chain.append({"id": job_id, "source_id": source_id, "step": f"custom_{ratio}", "target_id": ratio,
                          "prompt": prompt, "input_path": source["path"], "mask_path": str(full_mask)})
        jobs.extend(chain)
        source_jobs[source_id] = chain
    return source_ids, jobs, source_jobs, rule


def fit_output(path: Path, width: int, height: int) -> None:
    with Image.open(path) as image:
        result = ImageOps.pad(image.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS, color="white")
        temporary = path.with_suffix(path.suffix + '.tmp')
        result.save(temporary, "PNG")
    temporary.replace(path)
