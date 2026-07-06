"""
memory/vector_store.py – ChromaDB semantic layer for Klara's long-term memory.

Stores embedded memory chunks with metadata (timestamp, confidence, source).
Used for semantic search / RAG before each LLM reasoning cycle.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class VectorStore:
    """
    Thin wrapper around ChromaDB with an Ollama-backed embedding function.

    Falls back gracefully to a no-op stub when chromadb is not installed
    so the rest of the system can still boot for testing.
    """

    def __init__(
        self,
        persist_dir: str | Path,
        ollama_url: str,
        embedding_model: str,
        cache_size: int = 1024,
    ) -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.ollama_url = ollama_url
        self.embedding_model = embedding_model
        self._cache: dict[str, list[float]] = {}
        self._cache_size = cache_size
        self._client: Any = None
        self._collection: Any = None
        self._available = False
        self._init_chroma()

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def _init_chroma(self) -> None:
        try:
            import chromadb  # noqa: PLC0415
            from chromadb.config import Settings  # noqa: PLC0415

            self._client = chromadb.PersistentClient(
                path=str(self.persist_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name="klara_memory",
                metadata={"hnsw:space": "cosine"},
            )
            self._available = True
            log.info("ChromaDB initialized at %s", self.persist_dir)
        except ImportError:
            log.warning("chromadb not installed – vector store disabled.")
        except Exception as exc:
            log.error("ChromaDB init failed: %s", exc)

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list[float]:
        key = hashlib.sha256(text.encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]

        try:
            import httpx  # noqa: PLC0415

            r = httpx.post(
                f"{self.ollama_url.rstrip('/')}/api/embeddings",
                json={"model": self.embedding_model, "prompt": text},
                timeout=15.0,
            )
            r.raise_for_status()
            embedding: list[float] = r.json()["embedding"]
        except Exception as exc:
            log.warning("Embedding failed for text='%.60s…': %s", text, exc)
            return []

        if len(self._cache) >= self._cache_size:
            # Evict oldest entry (insertion-order dict in Python 3.7+)
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = embedding
        return embedding

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        doc_id: str | None = None,
        min_confidence: float = 0.0,
    ) -> bool:
        """
        Embed and store a memory chunk.

        Returns True on success, False on failure.
        """
        if not self._available:
            return False

        confidence = (metadata or {}).get("confidence", 1.0)
        if confidence < min_confidence:
            return False

        embedding = self._embed(text)
        if not embedding:
            return False

        _id = doc_id or hashlib.sha256(text.encode()).hexdigest()[:16]
        _meta = {
            "timestamp": datetime.utcnow().isoformat(),
            "confidence": float(confidence),
            "source": "auto",
            **(metadata or {}),
        }

        try:
            self._collection.upsert(
                ids=[_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[_meta],
            )
            return True
        except Exception as exc:
            log.error("ChromaDB upsert failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Retrieve the top_k most semantically similar documents.

        Returns list of {"document": str, "score": float, "metadata": dict}.
        """
        if not self._available:
            return []

        embedding = self._embed(query)
        if not embedding:
            return []

        try:
            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=min(top_k, self._collection.count() or 1),
                include=["documents", "distances", "metadatas"],
            )
        except Exception as exc:
            log.error("ChromaDB query failed: %s", exc)
            return []

        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metas = results.get("metadatas", [[]])[0]

        items: list[dict] = []
        for doc, dist, meta in zip(docs, distances, metas):
            score = 1.0 - dist  # cosine distance → similarity
            if score >= min_score:
                items.append({"document": doc, "score": score, "metadata": meta})

        items.sort(key=lambda x: x["score"], reverse=True)
        return items

    def count(self) -> int:
        if not self._available:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def delete(self, doc_id: str) -> None:
        if not self._available:
            return
        try:
            self._collection.delete(ids=[doc_id])
        except Exception as exc:
            log.warning("ChromaDB delete failed for id=%s: %s", doc_id, exc)
