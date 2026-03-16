from __future__ import annotations

import asyncio
import base64
import logging
from typing import Literal

from app.config import Settings

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None


class VisionAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._enabled = bool(settings.google_api_key and genai and types)
        self._client = genai.Client(api_key=settings.google_api_key) if self._enabled else None

    async def analyze_image(
        self,
        *,
        question: str,
        image_b64: str,
        mime_type: str,
        assistant_mode: Literal["general", "diy"],
    ) -> str | None:
        if not self._enabled or not self._client:
            return None

        prompt = self._build_prompt(question=question, assistant_mode=assistant_mode)
        image_bytes = base64.b64decode(image_b64)

        try:
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self.settings.vision_model,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                ],
                config=types.GenerateContentConfig(
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
                    system_instruction=(
                        "You are HoneyAI's visual grounding engine. Use only the latest attached image. "
                        "Ignore prior frames and earlier visual assumptions. If the image is unclear, say so plainly. "
                        "Return only a concise user-facing visual analysis. No chain-of-thought, no headings, no markdown."
                    ),
                ),
            )
        except Exception:
            logger.exception("High-resolution visual analysis failed")
            return None

        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            collected: list[str] = []
            for part in parts:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str) and part_text.strip():
                    collected.append(part_text.strip())
            if collected:
                return " ".join(collected)
        return None

    def _build_prompt(self, *, question: str, assistant_mode: Literal["general", "diy"]) -> str:
        mode_instructions = (
            "Focus on what the object, device, label, screen, or person in the latest image actually is, what details are visible, and what uncertainty remains."
            if assistant_mode == "general"
            else "Focus on visible devices, labels, ports, cables, controls, tool state, safety issues, and what the user should do next based only on the latest image."
        )
        return (
            f"User question: {question}\n"
            f"Assistant mode: {assistant_mode}\n"
            "Important: Answer from only the latest attached image. Do not use prior visual memory. "
            "If the image is ambiguous or blurry, say what is unclear instead of guessing. "
            f"{mode_instructions}"
        )

    async def validate_step(
        self,
        *,
        image_b64: str,
        mime_type: str,
        step_title: str,
        step_instruction: str,
        validation_hint: str,
    ) -> dict[str, str]:
        """
        Validates the user's progress for a specific task step using visual input.
        Returns a dict with 'status' (completed, blocked, in_progress) and 'reasoning'.
        """
        if not self._enabled or not self._client:
            return {"status": "in_progress", "reasoning": "Vision analyzer not enabled"}

        prompt = (
            f"Task Step: {step_title}\n"
            f"Step Instruction: {step_instruction}\n"
            f"Validation Criteria: {validation_hint}\n\n"
            "Analyze the latest image and determine if the user has successfully completed this step. "
            "Return a JSON object with exactly two fields:\n"
            "1. 'status': one of ['completed', 'blocked', 'in_progress']\n"
            "2. 'reasoning': a very short one-sentence explanation of what you see to justify the status."
        )

        image_bytes = base64.b64decode(image_b64)

        try:
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self.settings.vision_model,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
                    system_instruction=(
                        "You are a DIY repair validator. Your job is to look at the latest image and verify if the user has followed the specific instruction provided. "
                        "Be strict but fair. If the image is too blurry to be sure, return 'in_progress' with a reasoning asking the user for a clearer view. "
                        "Return ONLY valid JSON."
                    ),
                ),
            )
            
            # Use utility to parse response text as JSON
            import json
            result = json.loads(response.text)
            
            # Validate expected fields
            if "status" not in result or result["status"] not in ["completed", "blocked", "in_progress"]:
                result["status"] = "in_progress"
            if "reasoning" not in result:
                result["reasoning"] = "Could not determine status from visual input."
                
            return result
        except Exception:
            logger.exception("Visual step validation failed")
            return {"status": "in_progress", "reasoning": "Encountered an internal error during validation."}

