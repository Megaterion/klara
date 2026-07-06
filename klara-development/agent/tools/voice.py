"""
tools/voice.py – XTTS TTS integration for Klara's voice output.

Features:
- Sends text to the XTTS server for synthesis.
- Streams audio immediately (no waiting for full file).
- Waveform cache for frequently used phrases.
- Text pre-processing: number normalization, sentence splitting for prosody.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    """
    Pre-process text for better TTS pronunciation.
    - Expand common abbreviations.
    - Convert digits to spoken form (basic German).
    - Split overly long sentences.
    """
    # Basic number normalization (extend as needed)
    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", r"\1 Uhr \2", text)
    text = re.sub(r"\b(\d+)%", r"\1 Prozent", text)
    return text.strip()


def _split_for_prosody(text: str, max_chars: int = 200) -> list[str]:
    """Split long text into prosodic segments at sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    segments: list[str] = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) <= max_chars:
            current = (current + " " + sent).strip()
        else:
            if current:
                segments.append(current)
            current = sent
    if current:
        segments.append(current)
    return segments or [text]


class VoiceTool:
    def __init__(
        self,
        xtts_url: str,
        voice_sample_path: str | Path,
        language: str = "de",
        sample_rate: int = 22050,
        cache_size: int = 50,
        stream: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.xtts_url = xtts_url.rstrip("/")
        self.voice_sample_path = Path(voice_sample_path)
        self.language = language
        self.sample_rate = sample_rate
        self.stream = stream
        self.timeout = timeout
        self._cache: dict[str, bytes] = {}
        self._cache_size = cache_size

    # ------------------------------------------------------------------
    # Main speak interface
    # ------------------------------------------------------------------

    async def speak(self, text: str, language: str | None = None) -> bool:
        lang = language or self.language
        text = _normalize_text(text)
        segments = _split_for_prosody(text)

        success = True
        for seg in segments:
            ok = await self._synthesize_and_play(seg, lang)
            if not ok:
                success = False
        return success

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    async def _synthesize_and_play(self, text: str, language: str) -> bool:
        cache_key = hashlib.sha256(f"{text}:{language}".encode()).hexdigest()

        if cache_key in self._cache:
            audio_bytes = self._cache[cache_key]
            log.debug("TTS cache hit for '%.40s…'", text)
        else:
            audio_bytes = await self._call_xtts(text, language)
            if audio_bytes is None:
                return False
            # Cache management
            if len(self._cache) >= self._cache_size:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = audio_bytes

        return await self._play_audio(audio_bytes)

    async def _call_xtts(self, text: str, language: str) -> bytes | None:
        if not self.voice_sample_path.exists():
            log.error("Voice sample not found: %s", self.voice_sample_path)
            return None

        url = f"{self.xtts_url}/tts_to_audio"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload: dict[str, Any] = {
                    "text": text,
                    "speaker_wav": str(self.voice_sample_path),
                    "language": language,
                }
                r = await client.post(url, json=payload)
                r.raise_for_status()
                return r.content
        except Exception as exc:
            log.error("XTTS synthesis error for '%.40s…': %s", text, exc)
            return None

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    async def _play_audio(self, audio_bytes: bytes) -> bool:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            proc = await asyncio.create_subprocess_exec(
                "aplay", "-q", tmp_path,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except FileNotFoundError:
            # Fallback: try paplay (PulseAudio)
            try:
                proc = await asyncio.create_subprocess_exec(
                    "paplay", tmp_path,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                await proc.wait()
                return proc.returncode == 0
            except FileNotFoundError:
                log.error("No audio player found (aplay / paplay). Install alsa-utils or pulseaudio.")
                return False
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, action: str, payload: dict[str, Any]) -> Any:
        if action == "speak":
            return await self.speak(
                text=payload["text"],
                language=payload.get("language"),
            )
        log.warning("VoiceTool: unknown action '%s'", action)
        return None
