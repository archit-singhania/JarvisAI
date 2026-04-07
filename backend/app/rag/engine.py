"""
RAG Engine — Retrieval-Augmented Generation using ChromaDB (free, local).
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis.rag")


class RAGEngine:
    def __init__(self):
        from app.config import settings
        self.settings = settings
        self._collection = None
        self._embedder = None
        logger.info("RAGEngine initialised")

    @property
    def collection(self):
        if self._collection is None:
            import chromadb
            client = chromadb.PersistentClient(path=str(self.settings.VECTOR_DB_PATH))
            self._collection = client.get_or_create_collection(
                name="jarvis_memory",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"ChromaDB collection ready — {self._collection.count()} docs")
        return self._collection

    @property
    def embedder(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Embedding model loaded: all-MiniLM-L6-v2")
        return self._embedder

    async def add_document(
        self, text: str, doc_id: str, metadata: Optional[dict] = None
    ) -> bool:
        try:
            chunks = self._chunk_text(text)
            embeddings = self.embedder.encode(chunks).tolist()
            ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]

            # ChromaDB requires non-empty metadata dict — always include at least source
            safe_meta = metadata if (metadata and len(metadata) > 0) else {"source": doc_id}
            metas = [safe_meta for _ in chunks]

            self.collection.add(
                documents=chunks,
                embeddings=embeddings,
                ids=ids,
                metadatas=metas,
            )
            logger.info(f"Added {len(chunks)} chunks for doc '{doc_id}'")
            return True
        except Exception as e:
            logger.error(f"RAG add_document error: {e}")
            return False

    async def query(self, query_text: str, n_results: int = 3) -> Dict[str, Any]:
        try:
            if self.collection.count() == 0:
                return {"documents": [], "distances": []}

            embedding = self.embedder.encode([query_text]).tolist()
            results = self.collection.query(
                query_embeddings=embedding,
                n_results=min(n_results, self.collection.count()),
                include=["documents", "distances", "metadatas"],
            )
            docs = [
                {"content": doc, "distance": dist, "metadata": meta}
                for doc, dist, meta in zip(
                    results["documents"][0],
                    results["distances"][0],
                    results["metadatas"][0],
                )
            ]
            logger.info(f"RAG retrieved {len(docs)} chunks")
            return {"documents": docs}
        except Exception as e:
            logger.error(f"RAG query error: {e}")
            return {"documents": []}

    async def add_memory(self, key: str, value: str) -> bool:
        """Store a simple key=value memory (e.g. 'user name = Archit')."""
        return await self.add_document(
            text=f"{key}: {value}",
            doc_id=f"memory_{key.replace(' ', '_')}",
            metadata={"type": "memory", "key": key},
        )

    def _chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        words = text.split()
        if not words:
            return [text]
        chunks, i = [], 0
        while i < len(words):
            chunk = " ".join(words[i:i + chunk_size])
            chunks.append(chunk)
            i += chunk_size - overlap
        return chunks
