from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class ModelRegistry:
    def __init__(self, client: AsyncOpenAI, edit_candidate: str, draft_candidate: str) -> None:
        self.client = client
        self.candidates = {"edit": edit_candidate, "draft": draft_candidate}
        self.models: dict[str, dict[str, Any]] = {}
        self.capabilities = {
            "input_fidelity": "unknown",
            "background": "unknown",
            "output_compression": "unknown",
            "stream": "unknown",
        }

    async def initialize(self) -> None:
        try:
            response = await self.client.models.list()
        except Exception as exc:
            logger.error("Failed to list models from relay: %s", exc)
            raise RuntimeError("model list request failed") from exc

        available = {str(item.id) for item in response.data}
        for role, configured in self.candidates.items():
            resolved = self._resolve(configured, available)
            self.models[role] = {
                "configured": configured,
                "resolved": resolved,
                "available": resolved is not None,
            }

    @staticmethod
    def _resolve(configured: str, available: set[str]) -> str | None:
        if configured in available:
            return configured
        case_insensitive = [item for item in available if item.lower() == configured.lower()]
        if len(case_insensitive) == 1:
            logger.warning("Using case-insensitive model match '%s'", case_insensitive[0])
            return case_insensitive[0]
        candidates = sorted(item for item in available if "gpt-image-2.5" in item.lower())
        if len(candidates) == 1:
            logger.warning("Using unique image model candidate '%s'", candidates[0])
            return candidates[0]
        if len(candidates) > 1:
            logger.warning("Model '%s' is ambiguous: %s", configured, candidates)
        else:
            logger.warning("Model '%s' was not found", configured)
        return None

    def health(self) -> dict[str, Any]:
        edit_available = self.models.get("edit", {}).get("available", False)
        draft_available = self.models.get("draft", {}).get("available", False)
        status = "ok" if edit_available else "degraded"
        return {"status": status, "models": self.models, "capabilities": self.capabilities}

    def resolved_model(self, role: str = "edit") -> str:
        model = self.models.get(role, {}).get("resolved")
        if not model:
            raise RuntimeError(f"model role '{role}' is unavailable")
        return model

