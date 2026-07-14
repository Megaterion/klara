"""
ChromaDB-backed vector store for semantic memory retrieval.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class VectorStore:
    """Wraps ChromaDB for semantic storage and retrieval of Klara's memories."""

    def __init__(self, db_path: str, embedding_model: str = "nomic-embed-text") -> None:
        self.db_path = db_path
        self.embedding_model = embedding_model
        self._client = None
        self._collection = None

    async def open(self) -> None:
        import chromadb
        from chromadb.utils import embedding_functions

        Path(self.db_path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=self.db_path)

        # Use sentence-transformers for local embeddings (no API key needed)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self._collection = self._client.get_or_create_collection(
            name="klara_memories",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "VectorStore opened at %s (%d entries)",
            self.db_path,
            self._collection.count(),
        )

    async def close(self) -> None:
        # ChromaDB PersistentClient auto-persists; nothing to explicitly close
        self._client = None
        self._collection = None

    async def add(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[dict] = None,
    ) -> None:
        if self._collection is None:
            return
        self._collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )

    async def query(
        self,
        text: str,
        top_k: int = 10,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """Return top_k semantically similar memories."""
        if self._collection is None or self._collection.count() == 0:
            return []
        results = self._collection.query(
            query_texts=[text],
            n_results=min(top_k, self._collection.count()),
            where=where,
        )
        items = []
        for i, doc in enumerate(results["documents"][0]):
            items.append(
                {
                    "id": results["ids"][0][i],
                    "text": doc,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0.0,
                }
            )
        return items

    async def delete(self, doc_id: str) -> None:
        if self._collection:
            self._collection.delete(ids=[doc_id])
