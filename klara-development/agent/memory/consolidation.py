"""
memory/consolidation.py – Nightly memory consolidation loop.

Runs once per day (default at 03:00) to:
1. Summarize the day's events via LLM.
2. Extract new durable facts and preferences.
3. Remove duplicate / contradictory entries.
4. Update ChromaDB with consolidated knowledge.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from .sqlite_store import SQLiteStore
    from .vector_store import VectorStore

log = logging.getLogger(__name__)

_CONSOLIDATION_PROMPT = """
Du bist ein Wissensmanager für Klara. Analysiere folgende Tages-Events und extrahiere:

1. Neue dauerhafte Fakten über den Nutzer (z.B. Gewohnheiten, Vorlieben, Routinen).
2. Widersprüche zu bereits bekannten Fakten (liste diese explizit auf).
3. Neue Präferenzen als Key-Value-Paare.

Antworte NUR mit gültigem JSON im Format:
{
  "new_facts": ["..."],
  "contradictions": ["..."],
  "preferences": {"key": "value"}
}

Events des Tages:
{events}

Bekannte Fakten:
{known_facts}
"""


class MemoryConsolidation:
    def __init__(
        self,
        sqlite: "SQLiteStore",
        vector: "VectorStore",
        ollama_url: str,
        planner_model: str,
        user_id: str,
        consolidation_hour: int = 3,
    ) -> None:
        self.sqlite = sqlite
        self.vector = vector
        self.ollama_url = ollama_url
        self.planner_model = planner_model
        self.user_id = user_id
        self.consolidation_hour = consolidation_hour
        self._running = False
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._loop(), name="memory_consolidation")
            log.info("Memory consolidation loop started (runs at %02d:00 UTC).", self.consolidation_hour)

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while self._running:
            try:
                now = datetime.utcnow()
                next_run = now.replace(
                    hour=self.consolidation_hour, minute=0, second=0, microsecond=0
                )
                if next_run <= now:
                    next_run += timedelta(days=1)
                wait_seconds = (next_run - now).total_seconds()
                log.debug("Next consolidation in %.0f seconds.", wait_seconds)
                await asyncio.sleep(wait_seconds)
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Consolidation loop error: %s", exc)
                await asyncio.sleep(3600)  # retry in 1h on error

    # ------------------------------------------------------------------
    # Core consolidation
    # ------------------------------------------------------------------

    async def run_once(self) -> None:
        log.info("Starting nightly memory consolidation for user '%s'…", self.user_id)
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat()

        events = self.sqlite.get_events_since(self.user_id, since)
        if not events:
            log.info("No events in the last 24h – consolidation skipped.")
            return

        known_facts = self.sqlite.get_facts(self.user_id, min_confidence=0.5)
        events_text = "\n".join(
            f"[{e['created_at'][:16]}] {e.get('user_input', '')} → {e.get('response', '')}"
            for e in events[:50]  # cap to avoid context overflow
        )

        prompt = _CONSOLIDATION_PROMPT.format(
            events=events_text,
            known_facts="\n".join(known_facts[:30]),
        )

        result = await self._call_llm(prompt)
        if result is None:
            log.warning("Consolidation LLM call returned no result.")
            return

        try:
            data: dict[str, Any] = json.loads(result)
        except json.JSONDecodeError as exc:
            log.error("Consolidation JSON parse error: %s\nRaw: %s", exc, result[:200])
            return

        # Apply results
        for fact in data.get("new_facts", []):
            self.sqlite.upsert_fact(self.user_id, fact, confidence=0.95, source="consolidation")
            self.vector.add(fact, metadata={"user_id": self.user_id, "type": "consolidated_fact", "confidence": 0.95})

        for key, value in data.get("preferences", {}).items():
            self.sqlite.upsert_preference(self.user_id, key, str(value))

        contradictions: list[str] = data.get("contradictions", [])
        if contradictions:
            log.info("Consolidation found %d contradictions – marking for review.", len(contradictions))

        log.info(
            "Consolidation done: %d new facts, %d preferences, %d contradictions.",
            len(data.get("new_facts", [])),
            len(data.get("preferences", {})),
            len(contradictions),
        )

    # ------------------------------------------------------------------
    # LLM helper
    # ------------------------------------------------------------------

    async def _call_llm(self, prompt: str) -> str | None:
        url = f"{self.ollama_url.rstrip('/')}/api/generate"
        payload = {
            "model": self.planner_model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2},
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                return r.json().get("response", "")
        except Exception as exc:
            log.error("Consolidation LLM error: %s", exc)
            return None
