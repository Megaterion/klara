"""
main.py – Klara Agent Entry Point

Boots the full agent stack:
1. Load and merge config (base + profile).
2. Initialize all subsystems (memory, tools, safety, observability).
3. Start the EventBus and register event handlers.
4. Launch the Orchestrator.
5. Start the nightly memory consolidation loop.
6. Run the async event loop until SIGTERM/SIGINT.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

from .event_bus import Event, EventBus, EventType
from .memory.consolidation import MemoryConsolidation
from .memory.retrieval import MemoryRetrieval
from .memory.sqlite_store import SQLiteStore
from .memory.vector_store import VectorStore
from .observability.metrics import KlaraMetrics
from .observability.quality_checks import log_kpi_status
from .observability.tracing import configure_logging
from .orchestrator import Orchestrator
from .tools.filesystem import FilesystemTool
from .tools.internet import InternetTool
from .tools.smarthome import SmarthomeTool
from .tools.vision import VisionTool
from .tools.voice import VoiceTool

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config(profile: str | None = None) -> dict[str, Any]:
    base_dir = Path(__file__).parent.parent
    base_path = base_dir / "config" / "base.json"

    with base_path.open(encoding="utf-8") as f:
        cfg: dict[str, Any] = json.load(f)

    if profile:
        profile_path = base_dir / "config" / f"profile.{profile}.json"
        if profile_path.exists():
            with profile_path.open(encoding="utf-8") as f:
                override: dict[str, Any] = json.load(f)
            cfg = _deep_merge(cfg, override)

    # Inject env-var overrides for secrets
    if os.getenv("HOMEASSISTANT_URL"):
        cfg.setdefault("homeassistant", {})["url"] = os.environ["HOMEASSISTANT_URL"]
    if os.getenv("HOMEASSISTANT_TOKEN"):
        cfg.setdefault("homeassistant", {})["token"] = os.environ["HOMEASSISTANT_TOKEN"]

    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Timer event producer
# ---------------------------------------------------------------------------

async def _timer_producer(bus: EventBus, interval_seconds: int) -> None:
    """Periodically fire timer events to trigger autonomous checks."""
    log.info("Timer producer started (interval=%ds)", interval_seconds)
    while True:
        await asyncio.sleep(interval_seconds)
        await bus.publish(Event(type=EventType.TIMER, source="timer_producer"))


# ---------------------------------------------------------------------------
# Main bootstrap
# ---------------------------------------------------------------------------

async def run(profile: str | None = None) -> None:
    cfg = _load_config(profile)

    configure_logging(cfg.get("observability", {}).get("log_level", "INFO"))
    log.info("Starting Klara agent v%s (profile: %s)", cfg.get("version", "1.0.0"), profile or "base")

    # Paths
    base_dir = Path(__file__).parent.parent
    paths: dict[str, str] = cfg.get("paths", {})
    sqlite_path = base_dir / paths.get("sqlite_db", "shared-data/sqlite/klara.db")
    vector_path = base_dir / paths.get("vector_db", "shared-data/vector_db")
    voice_sample_path = (
        base_dir / paths.get("voice_samples", "shared-data/voice_samples")
        / cfg.get("tts", {}).get("voice_sample_file", "killjoy.wav")
    )

    # Memory layer
    sqlite = SQLiteStore(sqlite_path)
    vector = VectorStore(
        persist_dir=vector_path,
        ollama_url=cfg["ollama_url"],
        embedding_model=cfg["embedding_model"],
        cache_size=cfg.get("memory", {}).get("embedding_cache_size", 1024),
    )
    retrieval = MemoryRetrieval(
        sqlite=sqlite,
        vector=vector,
        top_k=cfg.get("memory", {}).get("retrieval_top_k", 10),
    )

    # Tools
    ha_cfg = cfg.get("homeassistant", {})
    smarthome = SmarthomeTool(
        ha_url=ha_cfg.get("url", ""),
        ha_token=ha_cfg.get("token", ""),
    )
    tts_cfg = cfg.get("tts", {})
    voice = VoiceTool(
        xtts_url=cfg["xtts_url"],
        voice_sample_path=voice_sample_path,
        language=tts_cfg.get("language", "de"),
        sample_rate=tts_cfg.get("sample_rate", 22050),
        cache_size=tts_cfg.get("waveform_cache_size", 50),
        stream=tts_cfg.get("stream_audio", True),
    )
    filesystem = FilesystemTool(
        allowed_roots=[str(base_dir), str(Path.home())],
        default_notes_dir=base_dir / "shared-data" / "notes",
    )
    vision = VisionTool(
        ollama_url=cfg["ollama_url"],
        vision_model=cfg["vision_model"],
        camera_index=cfg.get("camera_index", 0),
    )
    internet = InternetTool()

    # Metrics
    metrics = KlaraMetrics()

    # Orchestrator
    orchestrator = Orchestrator(
        cfg=cfg,
        sqlite=sqlite,
        retrieval=retrieval,
        metrics=metrics,
        smarthome=smarthome,
        voice=voice,
        filesystem=filesystem,
        vision=vision,
        internet=internet,
    )

    # Event bus
    bus = EventBus()
    bus.subscribe(EventType.TIMER, orchestrator.handle_event)
    bus.subscribe(EventType.USER_INPUT, orchestrator.handle_event)
    bus.subscribe(EventType.SMARTHOME_STATE_CHANGE, orchestrator.handle_event)
    bus.subscribe(EventType.MOTION_DETECTED, orchestrator.handle_event)

    # Nightly consolidation
    consolidation = MemoryConsolidation(
        sqlite=sqlite,
        vector=vector,
        ollama_url=cfg["ollama_url"],
        planner_model=cfg["llm_planner_model"],
        user_id=cfg.get("user_id", "master_chef"),
        consolidation_hour=cfg.get("memory", {}).get("consolidation_hour", 3),
    )
    consolidation.start()

    # Graceful shutdown
    stop_event = asyncio.Event()

    def _shutdown(*_: Any) -> None:
        log.info("Shutdown signal received.")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    # Announce startup
    await bus.publish(Event(type=EventType.SYSTEM_STARTUP, source="main"))

    # Launch all background tasks
    tasks = [
        asyncio.create_task(bus.run(), name="event_bus"),
        asyncio.create_task(
            _timer_producer(bus, cfg.get("check_interval_seconds", 300)),
            name="timer_producer",
        ),
    ]

    log.info("Klara is online. Waiting for events…")

    # Block until shutdown
    await stop_event.wait()

    # Cleanup
    log.info("Shutting down…")
    consolidation.stop()
    bus.stop()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    log_kpi_status(metrics)
    metrics.log_summary()
    log.info("Klara shutdown complete.")


def main() -> None:
    profile = os.getenv("KLARA_PROFILE", "dev")
    asyncio.run(run(profile=profile))


if __name__ == "__main__":
    main()
