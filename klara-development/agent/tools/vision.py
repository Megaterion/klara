"""
vision.py — Webcam capture + LLaVA vision analysis.
Trigger-based only — not continuously running.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import httpx

from agent.schemas.tool_contracts import ToolResult

logger = logging.getLogger(__name__)


class VisionAgent:
    def __init__(self, config: dict) -> None:
        self.camera_index: int = config.get("camera_index", 0)
        self.ollama_url: str = config.get("ollama_url", "http://localhost:11434")
        self.vision_model: str = config.get("vision_model", "llava:7b")
        self._timeout = config.get("tool_timeout_seconds", 30)
        self._client: Optional[httpx.AsyncClient] = None

    async def open(self) -> None:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        logger.info("VisionAgent ready (camera %d, model %s)", self.camera_index, self.vision_model)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def capture_and_describe(
        self, prompt: str = "Describe what you see briefly in 1-2 sentences."
    ) -> ToolResult:
        """Capture webcam frame and get LLaVA description."""
        import cv2  # import here to avoid hard dep at startup

        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            return ToolResult(tool="vision", success=False, error=f"Cannot open camera {self.camera_index}")

        try:
            ret, frame = cap.read()
            if not ret:
                return ToolResult(tool="vision", success=False, error="Failed to read frame")

            # Encode frame as JPEG
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            image_b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        finally:
            cap.release()

        # Send to Ollama LLaVA
        try:
            resp = await self._client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.vision_model,
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            description = resp.json().get("response", "")
            return ToolResult(tool="vision", success=True, data=description)
        except httpx.HTTPError as exc:
            logger.error("Vision LLaVA call failed: %s", exc)
            return ToolResult(tool="vision", success=False, error=str(exc))
