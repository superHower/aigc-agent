from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImageEditor:
    def __init__(self, client: AsyncOpenAI, model_registry: Any, snapshots_dir: Path, output_dir: Path) -> None:
        self.client = client
        self.model_registry = model_registry
        self.snapshots_dir = snapshots_dir
        self.output_dir = output_dir

    async def edit(
        self,
        *,
        job_id: str,
        input_path: Path,
        mask_path: Path,
        prompt: str,
        size: str,
        quality: str,
        output_format: str,
        request_timeout: float,
    ) -> tuple[Path, dict[str, Any]]:
        input_bytes = input_path.read_bytes()
        mask_bytes = mask_path.read_bytes()
        model = self.model_registry.resolved_model("edit")
        started_at = _utc_now()
        snapshot = {
            "job_id": job_id,
            "input_path": str(input_path),
            "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
            "mask_path": str(mask_path),
            "mask_sha256": hashlib.sha256(mask_bytes).hexdigest(),
            "prompt": prompt,
            "model": model,
            "size": size,
            "quality": quality,
            "output_format": output_format,
            "started_at": started_at,
        }
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self.snapshots_dir / f"{job_id}_input.json"
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        with input_path.open("rb") as image_file, mask_path.open("rb") as mask_file:
            result = await self.client.images.edit(
                model=model,
                image=image_file,
                mask=mask_file,
                prompt=prompt,
                size=size,
                quality=quality,
                output_format=output_format,
                n=1,
                timeout=request_timeout,
            )

        if not result.data:
            raise RuntimeError("image edit returned no output")
        item = result.data[0]
        encoded = getattr(item, "b64_json", None)
        if not encoded:
            raise RuntimeError("image edit returned no b64_json output")
        image_bytes = base64.b64decode(encoded)
        output_dir = self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{job_id}.{output_format}"
        output_path.write_bytes(image_bytes)
        snapshot.update(
            {
                "finished_at": _utc_now(),
                "output_path": str(output_path),
                "output_sha256": hashlib.sha256(image_bytes).hexdigest(),
            }
        )
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path, snapshot

