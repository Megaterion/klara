"""
Nightly memory consolidation job.
Runs at consolidation_hour (default 3 AM) to:
- Remove duplicate facts
- Resolve contradictions using recency weighting
- Update preference frequency scores
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.memory.sqlite_store import SQLiteStore
    from agent.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryConsolidation:
    def __init__(
        self,
        sqlite: "SQLiteStore",
        vector: "VectorStore",
        consolidation_hour: int = 3,
    ) -> None:
        self.sqlite = sqlite
        self.vector = vector
        self.consolidation_hour = consolidation_hour
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run_loop(), name="consolidation")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run_loop(self) -> None:
        """Wait until consolidation_hour, then run, then repeat daily."""
        while True:
            try:
                seconds_until = self._seconds_until_next_run()
                logger.info(
                    "Memory consolidation scheduled in %.0f minutes",
                    seconds_until / 60,
                )
                await asyncio.sleep(seconds_until)
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Consolidation error: %s", exc, exc_info=True)
                await asyncio.sleep(3600)  # retry in 1h on error

    def _seconds_until_next_run(self) -> float:
        now = datetime.now()
        target = now.replace(
            hour=self.consolidation_hour, minute=0, second=0, microsecond=0
        )
        if now >= target:
            # Schedule for tomorrow
            from datetime import timedelta
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def run_once(self) -> None:
        """Execute one full consolidation pass."""
        logger.info("Starting memory consolidation...")

        # 1. Decay preference recency scores
        await self._decay_preferences()

        # 2. Remove very old, low-confidence facts
        await self._prune_old_facts()

        logger.info("Memory consolidation complete.")

    async def _decay_preferences(self) -> None:
        """Apply time-based recency decay to preferences."""
        if not getattr(self.sqlite, "_db", None):
            return
        try:
            await self.sqlite._db.execute(
                   SET recency = recency * 0.95
                   WHERE recency > 0.01"""
            )
            await self.sqlite._db.commit()
        except Exception as exc:
            logger.warning("Preference decay failed: %s", exc)

    async def _prune_old_facts(self) -> None:
        """Remove user facts older than 90 days with low confidence."""
        if not getattr(self.sqlite, "_db", None):
            return
        try:
            await self.sqlite._db.execute(
                   WHERE confidence < 0.3
                   AND created_at < datetime('now', '-90 days')"""
            )
            await self.sqlite._db.commit()
        except Exception as exc:
            logger.warning("Fact pruning failed: %s", exc)
