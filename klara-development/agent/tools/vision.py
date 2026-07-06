"""
tools/vision.py – Webcam capture and scene description (v2.0 feature).

Trigger-based: Klara only captures a frame when explicitly requested
(motion event, user request, or smarthome trigger) – not continuously.
"""

from __future__ import annotations

import base64
import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)


class VisionTool:
    def __init__(
        self,
        ollama_url: str,
        vision_model: str,
        camera_index: int = 0,
        timeout: float = 30.0,
    ) -> None:
        self.ollama_url = ollama_url.rstrip("/")
        self.vision_model = vision_model
        self.camera_index = camera_index
        self.timeout = timeout

    async def capture_and_describe(self, camera_index: int | None = None) -> str | None:
        """Capture one frame from webcam and return a text description."""
        idx = camera_index if camera_index is not None else self.camera_index
        image_bytes = await self._capture_frame(idx)
        if image_bytes is None:
            return None
        return await self._describe_image(image_bytes)

    async def _capture_frame(self, camera_index: int) -> bytes | None:
        try:
            import cv2  # type: ignore[import-untyped]  # noqa: PLC0415
        except ImportError:
            log.warning("opencv-python not installed – vision tool disabled.")
            return None

        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            log.error("Cannot open camera index %d", camera_index)
            return None
        ret, frame = cap.read()
        cap.release()
        if not ret:
            log.error("Failed to read frame from camera %d", camera_index)
            return None

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            cv2.imwrite(tmp.name, frame)
            image_bytes = Path(tmp.name).read_bytes()
            Path(tmp.name).unlink(missing_ok=True)
        return image_bytes

    async def _describe_image(self, image_bytes: bytes) -> str | None:
        image_b64 = base64.b64encode(image_bytes).decode()
        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": self.vision_model,
            "prompt": "Beschreibe kurz und sachlich, was du auf diesem Bild siehst. Fokus auf Personen, Aktivitäten und relevante Objekte. Maximal 3 Sätze.",
            "images": [image_b64],
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                return r.json().get("response", "").strip()
        except Exception as exc:
            log.error("Vision describe error: %s", exc)
            return None

    async def dispatch(self, action: str, payload: dict[str, Any]) -> Any:
        if action == "capture_and_describe":
            return await self.capture_and_describe(payload.get("camera_index"))
        log.warning("VisionTool: unknown action '%s'", action)
        return None
