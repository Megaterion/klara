"""
ChromaDB-backed vector store for semantic memory retrieval.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class _OllamaEmbeddingFunction:
    def __init__(self, base_url: str, model_name: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout

    def __call__(self, input: list[str]) -> list[list[float]]:
        texts = list(input)
        if not texts:
            return []

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model_name, "input": texts},
            )
            if response.status_code == 404:
                return [self._embed_legacy(client, text) for text in texts]

            response.raise_for_status()
            payload = response.json()
            embeddings = payload.get("embeddings")
            if isinstance(embeddings, list) and embeddings:
                return embeddings

        raise ValueError("Ollama embed response did not include embeddings")

    def _embed_legacy(self, client: httpx.Client, text: str) -> list[float]:
        response = client.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model_name, "prompt": text},
        )
        response.raise_for_status()
        payload = response.json()
        embedding = payload.get("embedding")
        if isinstance(embedding, list) and embedding:
            return embedding
        raise ValueError("Legacy Ollama embedding response did not include embedding")


class VectorStore:
    """Wraps ChromaDB for semantic storage and retrieval of Klara's memories."""

    def __init__(
        self,
        db_path: str,
        embedding_model: str = "nomic-embed-text",
        ollama_url: str = "http://localhost:11434",
        fallback_model: str = "all-MiniLM-L6-v2",
    ) -> None:
        self.db_path = db_path
        self.embedding_model = embedding_model
        self.ollama_url = ollama_url
        self.fallback_model = fallback_model
        self._client = None
        self._collection = None

    async def open(self) -> None:
        import chromadb
        from chromadb.utils import embedding_functions

        Path(self.db_path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=self.db_path)

        ef = self._build_embedding_function(embedding_functions)
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

    def _build_embedding_function(self, embedding_functions):
        configured = self.embedding_model.strip()
        if configured:
            ollama_ef = _OllamaEmbeddingFunction(
                base_url=self.ollama_url,
                model_name=configured,
            )
            try:
                ollama_ef(["klara embedding probe"])
                logger.info("VectorStore embeddings via Ollama model: %s", configured)
                return ollama_ef
            except Exception as exc:
                logger.warning(
                    "Falling back to local sentence-transformers embeddings after Ollama failure for %s: %s",
                    configured,
                    exc,
                )

        logger.info("VectorStore embeddings via local model: %s", self.fallback_model)
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=self.fallback_model
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
