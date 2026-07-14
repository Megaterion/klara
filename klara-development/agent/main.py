"""
main.py — Klara v1.0 entry point.

Starts:
- Live Rich console UI
- Microphone capture loop (sounddevice + VAD)
- Whisper STT
- Orchestrator (LLM streaming + tools)
- Proactive timer cycle
- Nightly memory consolidation

Run with:
    KLARA_PROFILE=dev python -m agent.main
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Config loading                                                      #
# ------------------------------------------------------------------ #

def load_config(profile: str | None = None) -> dict:
    from dotenv import load_dotenv  # noqa: PLC0415

    base_dir = Path(__file__).parent.parent
    # Load .env from the project root (silently ignored if absent)
    load_dotenv(base_dir / ".env", override=False)

    profile = profile or os.environ.get("KLARA_PROFILE", "dev")
    base_path = base_dir / "config" / "base.json"
    profile_path = base_dir / "config" / f"profile.{profile}.json"

    with open(base_path, encoding="utf-8") as f:
        config = json.load(f)

    if profile_path.exists():
        with open(profile_path, encoding="utf-8") as f:
            overrides = json.load(f)
        _deep_merge(config, overrides)

    # Apply environment-variable overrides for sensitive / installation-specific settings
    if ha_url := os.environ.get("HA_URL"):
        config.setdefault("homeassistant", {})["url"] = ha_url
    if ha_token := os.environ.get("HA_TOKEN"):
        config.setdefault("homeassistant", {})["token"] = ha_token

    config["_profile"] = profile
    return config


def _deep_merge(base: dict, overrides: dict) -> None:
    for k, v in overrides.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ------------------------------------------------------------------ #
#  Application                                                         #
# ------------------------------------------------------------------ #

class KlaraApp:
    def __init__(self, config: dict) -> None:
        self.config = config
        self._shutdown = asyncio.Event()

    async def run(self) -> None:
        from agent.event_bus import EventBus
        from agent.memory.consolidation import MemoryConsolidation
        from agent.memory.retrieval import MemoryRetrieval
        from agent.memory.sqlite_store import SQLiteStore
        from agent.memory.vector_store import VectorStore
        from agent.observability.console_ui import ConsoleUI
        from agent.observability.metrics import Metrics
        from agent.observability.tracing import StructuredLogger
        from agent.orchestrator import Orchestrator

        # --- Console UI (must start before logging) ---
        ui = ConsoleUI()
        ui.start()

        # --- Logging ---
        tracer = StructuredLogger(
            log_level=self.config.get("log_level", "INFO"),
            log_file=self.config.get("log_file"),
            log_max_bytes=self.config.get("log_max_bytes", 2 * 1024 * 1024),
            log_backup_count=self.config.get("log_backup_count", 2),
        )
        tracer.configure(ui=ui)
        logger.info(
            "Klara v1.0 starting — profile: %s, model: %s",
            self.config["_profile"],
            self.config["llm_model"],
        )

        # --- Memory ---
        sqlite = SQLiteStore(self.config["memory"]["sqlite_path"])
        await sqlite.open()

        vector = VectorStore(
            db_path=self.config["memory"]["vector_db_path"],
            embedding_model=self.config.get("embedding_model", "nomic-embed-text"),
            ollama_url=self.config.get("ollama_url", "http://localhost:11434"),
        )
        await vector.open()

        retrieval = MemoryRetrieval(
            sqlite=sqlite,
            vector=vector,
            top_k=self.config["memory"].get("retrieval_top_k", 10),
        )

        consolidation = MemoryConsolidation(
            sqlite=sqlite,
            vector=vector,
            consolidation_hour=self.config["memory"].get("consolidation_hour", 3),
        )
        consolidation.start()

        # --- Core ---
        bus = EventBus()
        metrics = Metrics()
        orchestrator = Orchestrator(
            config=self.config,
            ui=ui,
            bus=bus,
            sqlite=sqlite,
            retrieval=retrieval,
            metrics=metrics,
        )
        await orchestrator.open()

        ui.set_status("Bereit")
        ui.log_info(f"Profil: {self.config['_profile']} | Modell: {self.config['llm_model']}")
        ui.log_info("Klara ist bereit. Spreche jetzt.")

        # --- Signal handlers ---
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._request_shutdown)

        # --- Run all concurrent tasks ---
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._mic_loop(orchestrator, ui), name="mic_loop")
                tg.create_task(self._proactive_loop(orchestrator, ui), name="proactive_loop")
                tg.create_task(self._shutdown_waiter(), name="shutdown_waiter")
        except* asyncio.CancelledError:
            pass
        except* Exception as eg:
            for exc in eg.exceptions:
                logger.error("Fatal error: %s", exc, exc_info=exc)
        finally:
            logger.info("Shutting down…")
            consolidation.stop()
            await orchestrator.close()
            await sqlite.close()
            await vector.close()
            summary = metrics.summary()
            if summary:
                logger.info("Metrics summary: %s", summary)
            ui.set_status("Heruntergefahren")
            ui.stop()

    def _request_shutdown(self) -> None:
        logger.info("Shutdown signal received")
        self._shutdown.set()

    async def _shutdown_waiter(self) -> None:
        await self._shutdown.wait()
        raise asyncio.CancelledError("Shutdown requested")

    # ------------------------------------------------------------------ #
    #  Microphone loop                                                     #
    # ------------------------------------------------------------------ #

    async def _mic_loop(self, orchestrator: "Orchestrator", ui: "ConsoleUI") -> None:
        """
        Continuously listens for user speech.
        Uses VAD to detect utterances, then transcribes with faster-whisper.
        Partial transcription text is streamed live to the console while the
        user is speaking; a final transcription is shown once the utterance ends.
        """
        voice = orchestrator.voice
        logger.info("Microphone loop started")

        while not self._shutdown.is_set():
            try:
                def on_status(status: str) -> None:
                    ui.set_transcription("", status)

                def on_partial(text: str) -> None:
                    ui.set_transcription(text)

                utterance = await voice.listen_once(on_partial=on_partial, on_status=on_status)

                if not utterance or len(utterance.strip()) < 2:
                    ui.clear_transcription()
                    continue

                ui.set_transcription(utterance)
                logger.info("User said: %s", utterance)

                await orchestrator.process_user_input(utterance)
                ui.clear_transcription()

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Mic loop error: %s", exc, exc_info=True)
                await asyncio.sleep(1)

    # ------------------------------------------------------------------ #
    #  Proactive loop                                                      #
    # ------------------------------------------------------------------ #

    async def _proactive_loop(self, orchestrator: "Orchestrator", ui: "ConsoleUI") -> None:
        """
        Periodic proactive check: let Klara assess the world without user input.
        """
        interval = self.config.get("check_interval_seconds", 300)
        logger.info("Proactive loop started (interval: %ds)", interval)

        await asyncio.sleep(30)  # Initial delay before first check

        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(interval)
                if self._shutdown.is_set():
                    break
                ui.set_status("Proaktiver Check…")
                await orchestrator.run_proactive_cycle()
                ui.set_status("Bereit")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Proactive loop error: %s", exc, exc_info=True)


# ------------------------------------------------------------------ #
#  Entry point                                                         #
# ------------------------------------------------------------------ #

def main() -> None:
    profile = os.environ.get("KLARA_PROFILE", "dev")
    try:
        config = load_config(profile)
    except FileNotFoundError as exc:
        print(f"❌ Config file not found: {exc}", file=sys.stderr)
        print(
            "   Make sure you run from the klara-development/ directory "
            "or that config/base.json exists.",
            file=sys.stderr,
        )
        sys.exit(1)

    app = KlaraApp(config)
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
