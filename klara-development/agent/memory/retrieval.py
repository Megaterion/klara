"""
memory/retrieval.py – Hybrid retrieval combining SQLite facts and ChromaDB vectors.

Called before every LLM reasoning cycle to inject relevant context.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..schemas.world_state import MemoryContext

if TYPE_CHECKING:
    from .sqlite_store import SQLiteStore
    from .vector_store import VectorStore

log = logging.getLogger(__name__)


class MemoryRetrieval:
    """
    Combines:
    1. Structured facts from SQLite (always included).
    2. Semantic search results from ChromaDB (top_k, reranked).
    """

    def __init__(
        self,
        sqlite: "SQLiteStore",
        vector: "VectorStore",
        top_k: int = 10,
    ) -> None:
        self.sqlite = sqlite
        self.vector = vector
        self.top_k = top_k

    def retrieve(self, user_id: str, query: str) -> MemoryContext:
        """
        Build a MemoryContext for the given user and query.

        Steps:
        1. Fetch all structured facts from SQLite.
        2. Fetch user preferences from SQLite.
        3. Semantic search in ChromaDB using query.
        4. Merge and deduplicate.
        """
        # 1. Structured facts
        facts = self.sqlite.get_facts(user_id, min_confidence=0.5)

        # 2. Preferences → format as human-readable strings
        raw_prefs = self.sqlite.get_preferences(user_id)
        pref_strings = [
            f"{p['key']}: {p['value']} (x{p['frequency']})" for p in raw_prefs
        ]

        # 3. Semantic retrieval
        sem_results = self.vector.retrieve(query=query, top_k=self.top_k, min_score=0.3)
        sem_docs = [r["document"] for r in sem_results]

        # 4. Recent events as context
        recent = self.sqlite.get_recent_events(user_id, limit=5)
        recent_lines: list[str] = []
        for evt in recent:
            ui = evt.get("user_input") or ""
            resp = evt.get("response") or ""
            if ui or resp:
                recent_lines.append(f"[{evt['created_at'][:16]}] User: {ui} | Klara: {resp[:100]}")

        # Merge semantic docs into facts (dedup)
        all_facts = list(dict.fromkeys(facts + sem_docs))

        log.debug(
            "Memory retrieval: %d facts, %d prefs, %d semantic hits, %d recent events",
            len(all_facts),
            len(pref_strings),
            len(sem_docs),
            len(recent_lines),
        )

        return MemoryContext(
            facts=all_facts[: self.top_k],
            preferences=pref_strings,
            recent_events=recent_lines,
        )

    def store_cycle(
        self,
        user_id: str,
        user_input: str | None,
        response: str | None,
        extracted_facts: list[str] | None = None,
        min_confidence_to_vectorize: float = 0.6,
    ) -> None:
        """
        Persist a completed reasoning cycle to both stores.

        - Logs the event in SQLite.
        - Vectorizes the response if it contains meaningful content.
        - Optionally stores extracted facts.
        """
        event_text = (user_input or "") + " " + (response or "")
        if event_text.strip():
            self.vector.add(
                text=event_text.strip(),
                metadata={
                    "user_id": user_id,
                    "type": "event",
                    "confidence": 0.7,
                },
                min_confidence=min_confidence_to_vectorize,
            )

        if extracted_facts:
            for fact in extracted_facts:
                self.sqlite.upsert_fact(user_id, fact, confidence=0.9, source="llm_extract")
                self.vector.add(
                    text=fact,
                    metadata={"user_id": user_id, "type": "fact", "confidence": 0.9},
                    min_confidence=min_confidence_to_vectorize,
                )
