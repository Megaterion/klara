"""
Memory retrieval: combines SQLite facts with vector similarity search.
Prepares the MemoryContext that is injected into every LLM prompt.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agent.schemas.world_state import MemoryContext

if TYPE_CHECKING:
    from agent.memory.sqlite_store import SQLiteStore
    from agent.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryRetrieval:
    def __init__(
        self,
        sqlite: "SQLiteStore",
        vector: "VectorStore",
        top_k: int = 10,
    ) -> None:
        self.sqlite = sqlite
        self.vector = vector
        self.top_k = top_k

    async def retrieve(self, query: str) -> MemoryContext:
        """
        Build a MemoryContext for the given query.
        Combines:
        - Recent events (last N from SQLite)
        - Semantically relevant facts from vector store
        - User preferences from SQLite
        """
        # Recent episodic events
        recent_rows = await self.sqlite.get_recent_events(limit=5)
        recent_events = []
        for row in recent_rows:
            msg = row.get("user_message") or ""
            trigger = row.get("trigger", "")
            ts = row.get("timestamp", "")[:16]
            if msg:
                recent_events.append(f"[{ts}] {trigger}: {msg}")
            else:
                recent_events.append(f"[{ts}] {trigger}")

        # Semantic memory retrieval
        vector_hits = await self.vector.query(query, top_k=self.top_k)
        relevant_facts = [hit["text"] for hit in vector_hits if hit["distance"] < 0.5]

        # Hard-stored user facts (high-confidence ones)
        stored_facts = await self.sqlite.get_user_facts(limit=20)
        # Merge stored facts into relevant_facts (dedup)
        fact_set = set(relevant_facts)
        for f in stored_facts:
            if f not in fact_set:
                relevant_facts.append(f)
                fact_set.add(f)

        # Preferences
        prefs = await self.sqlite.get_preferences()
        pref_lines = [f"{k}: {v}" for k, v in list(prefs.items())[:10]]

        return MemoryContext(
            recent_events=recent_events,
            relevant_facts=relevant_facts[: self.top_k],
            preferences=pref_lines,
        )

    async def store_memory(
        self,
        text: str,
        source: str = "inference",
        metadata: dict | None = None,
    ) -> None:
        """Persist a new memory to both SQLite and vector store."""
        import hashlib

        doc_id = hashlib.sha256(text.encode()).hexdigest()[:16]
        meta = {"source": source, **(metadata or {})}
        await self.sqlite.upsert_user_fact(text, source=source)
        await self.vector.add(doc_id, text, meta)
        logger.debug("Stored memory: %s", text[:80])
