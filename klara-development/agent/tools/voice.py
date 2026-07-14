"""
voice.py — TTS + STT pipeline for Klara.

CRITICAL FIXES implemented here:
- Correct XTTS sample rate: 24000 Hz (NEVER resample)
- Audio parsed as float32 from WAV — never treated as int16
- Normalization before playback to prevent clipping/distortion
- Sentence chunking + async pipeline: generate chunk N+1 while playing chunk N
- VAD-based microphone capture with faster-whisper transcription
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import threading
import time
from typing import AsyncIterator, Callable, Optional

import httpx
import numpy as np
import sounddevice as sd
import soundfile as sf

logger = logging.getLogger(__name__)

# XTTS always outputs at this rate — never change it
XTTS_SAMPLE_RATE = 24000
# Microphone capture rate for faster-whisper (expects 16 kHz)
MIC_SAMPLE_RATE = 16000
# VAD frame duration in milliseconds (must be 10, 20, or 30)
VAD_FRAME_MS = 30
# How many consecutive silent frames signal end of speech
VAD_SILENCE_FRAMES = 20


class VoiceAgent:
    """
    Handles:
    - Text-to-speech via XTTS server (with distortion fixes)
    - Speech-to-text via faster-whisper + webrtcvad microphone capture
    """

    def __init__(self, config: dict) -> None:
        self.xtts_url: str = config["xtts_url"]
        self.voice_sample: str = config["voice_sample"]
        self.voice_language: str = config.get("voice_language", "de")
        tts_cfg = config.get("tts", {})
        self.chunk_min: int = tts_cfg.get("chunk_min_chars", 20)
        self.chunk_max: int = tts_cfg.get("chunk_max_chars", 150)
        self.normalize: bool = tts_cfg.get("normalize_volume", True)
        self.target_volume: float = tts_cfg.get("target_volume", 0.85)
        stt_cfg = config.get("stt", {})
        self.stt_model_size: str = stt_cfg.get("model", "base")
        self.stt_language: str = stt_cfg.get("language", "de")
        self.stt_device: str = stt_cfg.get("device", "cpu")
        self.stt_compute_type: str = stt_cfg.get("compute_type", "int8")
        self._whisper = None
        self._vad = None
        self._http_client: Optional[httpx.AsyncClient] = None
        # Playback lock — only one audio stream at a time
        self._play_lock = threading.Lock()

    async def open(self) -> None:
        self._http_client = httpx.AsyncClient(timeout=60.0)
        await self._init_stt()
        logger.info("VoiceAgent ready")

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()

    # ------------------------------------------------------------------ #
    #  STT                                                                 #
    # ------------------------------------------------------------------ #

    async def _init_stt(self) -> None:
        from faster_whisper import WhisperModel
        import webrtcvad

        loop = asyncio.get_event_loop()
        logger.info(
            "Loading Whisper model '%s' on %s (%s)...",
            self.stt_model_size,
            self.stt_device,
            self.stt_compute_type,
        )
        self._whisper = await loop.run_in_executor(
            None,
            lambda: WhisperModel(
                self.stt_model_size,
                device=self.stt_device,
                compute_type=self.stt_compute_type,
            ),
        )
        self._vad = webrtcvad.Vad(2)  # aggressiveness 0-3
        logger.info("Whisper model loaded.")

    async def transcribe_audio(self, audio_bytes: bytes) -> str:
        """Transcribe raw 16-bit mono PCM bytes at MIC_SAMPLE_RATE."""
        if self._whisper is None:
            return ""
        pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        loop = asyncio.get_event_loop()
        segments, _ = await loop.run_in_executor(
            None,
            lambda: self._whisper.transcribe(
                pcm,
                language=self.stt_language,
                beam_size=5,
                vad_filter=True,
            ),
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    async def listen_once(
        self,
        on_partial: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Capture one utterance from the microphone using VAD.
        Returns transcribed text.
        on_partial: called with a status string while listening (e.g. "Listening…")
        """
        frame_samples = int(MIC_SAMPLE_RATE * VAD_FRAME_MS / 1000)
        frames: list[bytes] = []
        speech_started = False
        silent_count = 0

        audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        loop = asyncio.get_event_loop()
        stop_event = threading.Event()

        def sd_callback(indata: np.ndarray, _frames: int, _time, _status) -> None:
            mono = indata[:, 0].copy()
            pcm16 = (mono * 32767).astype(np.int16)
            loop.call_soon_threadsafe(audio_queue.put_nowait, pcm16.tobytes())

        if on_partial:
            on_partial("🎤 Warte auf Sprache…")

        with sd.InputStream(
            samplerate=MIC_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=frame_samples,
            callback=sd_callback,
        ):
            while not stop_event.is_set():
                frame_bytes = await audio_queue.get()

                if len(frame_bytes) < frame_samples * 2:
                    continue

                try:
                    is_speech = self._vad.is_speech(frame_bytes, MIC_SAMPLE_RATE)
                except Exception:
                    is_speech = False

                if is_speech:
                    if not speech_started:
                        speech_started = True
                        if on_partial:
                            on_partial("🎤 Höre zu…")
                    silent_count = 0
                    frames.append(frame_bytes)
                elif speech_started:
                    frames.append(frame_bytes)
                    silent_count += 1
                    if silent_count >= VAD_SILENCE_FRAMES:
                        break  # End of utterance

        if not frames:
            return ""

        raw_audio = b"".join(frames)
        if on_partial:
            on_partial("📝 Transkribiere…")
        return await self.transcribe_audio(raw_audio)

    # ------------------------------------------------------------------ #
    #  TTS                                                                 #
    # ------------------------------------------------------------------ #

    async def speak(self, text: str) -> None:
        """
        Speak the given text via XTTS.
        Chunks the text and pipelines generation + playback to minimize latency.
        """
        if not text.strip():
            return

        chunks = self._split_into_chunks(text)
        if not chunks:
            return

        logger.info("TTS: speaking %d chunk(s) for %d chars", len(chunks), len(text))

        # Pipeline: producer fills the queue, consumer plays audio
        audio_queue: asyncio.Queue[Optional[np.ndarray]] = asyncio.Queue(maxsize=3)

        async def producer() -> None:
            for chunk in chunks:
                t0 = time.perf_counter()
                audio = await self._generate_audio(chunk)
                elapsed = (time.perf_counter() - t0) * 1000
                if audio is not None:
                    logger.debug("Generated %.0fms for %d chars", elapsed, len(chunk))
                    await audio_queue.put(audio)
                else:
                    logger.warning("TTS failed for chunk: %r", chunk[:40])
            await audio_queue.put(None)  # Sentinel: done generating

        async def consumer() -> None:
            while True:
                audio = await audio_queue.get()
                if audio is None:
                    break
                # Blocking playback runs in thread pool so the event loop stays free
                # for the producer to continue generating the next chunk
                await asyncio.get_event_loop().run_in_executor(
                    None, self._play_audio, audio
                )

        await asyncio.gather(producer(), consumer())

    async def _generate_audio(self, text: str) -> Optional[np.ndarray]:
        """
        Call XTTS server and return normalized float32 audio at 24000 Hz.

        DISTORTION FIXES:
        1. Parse WAV with soundfile (handles float32 correctly)
        2. Normalize amplitude before playback
        3. NEVER resample — XTTS outputs exactly 24000 Hz
        """
        if not self._http_client:
            return None
        try:
            resp = await self._http_client.post(
                f"{self.xtts_url}/api/tts",
                json={
                    "text": text,
                    "speaker_wav": self.voice_sample,
                    "language": self.voice_language,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("XTTS request failed: %s", exc)
            return None

        wav_bytes = resp.content
        if not wav_bytes:
            logger.warning("XTTS returned empty audio")
            return None

        try:
            audio, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
        except Exception as exc:
            logger.error("Failed to decode WAV: %s", exc)
            return None

        if sr != XTTS_SAMPLE_RATE:
            # Log but do not resample — mismatched rate means server misconfiguration
            logger.warning(
                "Unexpected sample rate from XTTS: %d Hz (expected %d). "
                "Audio may sound wrong. Check your XTTS model version.",
                sr,
                XTTS_SAMPLE_RATE,
            )

        # Ensure mono float32
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = audio.astype(np.float32)

        # Normalize to prevent clipping/distortion
        if self.normalize:
            peak = np.max(np.abs(audio))
            if peak > 1e-8:
                audio = audio / peak * self.target_volume

        return audio

    def _play_audio(self, audio: np.ndarray) -> None:
        """
        Blocking playback on the current default output device.
        MUST run in a thread (called via run_in_executor).
        Uses EXACTLY XTTS_SAMPLE_RATE (24000 Hz) — never resample.
        """
        with self._play_lock:
            try:
                sd.play(audio, samplerate=XTTS_SAMPLE_RATE, blocking=True)
            except sd.PortAudioError as exc:
                logger.error("Audio playback error: %s", exc)

    # ------------------------------------------------------------------ #
    #  Text chunking                                                       #
    # ------------------------------------------------------------------ #

    def _split_into_chunks(self, text: str) -> list[str]:
        """
        Split text into chunks suitable for XTTS generation.
        - Split at sentence boundaries: '. ', '! ', '? ', '\n'
        - Also split long clauses at ', ' when chunk exceeds chunk_max
        - Merge very short chunks (< chunk_min) with next chunk
        """
        # First pass: split at hard sentence boundaries
        raw = re.split(r"(?<=[.!?])\s+", text.strip())
        chunks: list[str] = []

        for sentence in raw:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= self.chunk_max:
                chunks.append(sentence)
            else:
                # Long sentence: split at commas
                parts = re.split(r",\s+", sentence)
                current = ""
                for part in parts:
                    if not current:
                        current = part
                    elif len(current) + len(part) + 2 <= self.chunk_max:
                        current += ", " + part
                    else:
                        if len(current) >= self.chunk_min:
                            chunks.append(current)
                        current = part
                if current:
                    chunks.append(current)

        # Second pass: merge chunks that are too short
        merged: list[str] = []
        for chunk in chunks:
            if merged and len(merged[-1]) < self.chunk_min:
                merged[-1] += " " + chunk
            else:
                merged.append(chunk)

        return [c.strip() for c in merged if c.strip()]
