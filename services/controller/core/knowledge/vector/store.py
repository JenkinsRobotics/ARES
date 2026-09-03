"""LanceDB vector store with hybrid (BM25 + vector) search.

Stores document chunks and their embeddings in a LanceDB table on the NAS.
Supports both semantic vector search and full-text keyword search,
plus a hybrid fusion mode that combines both.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..config import KBConfig
from .chunker import TextChunk, chunk_text
from .embedder import Embedder, EmbeddingError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    text: str
    source: str
    source_type: str
    heading: str
    score: float
    chunk_index: int
    # New metadata fields
    title: str = ""
    domain: str = ""
    tags: str = ""
    keywords: str = ""
    doc_id: str = ""
    content_format: str = ""


class KnowledgeStore:
    """LanceDB-backed vector store with hybrid search."""

    def __init__(self, config: KBConfig, embedder: Embedder | None = None) -> None:
        self.config = config
        self.embedder = embedder or Embedder.from_config(config)
        self._db = None
        self._table = None

    def _connect(self):
        """Lazy-connect to LanceDB."""
        if self._db is not None:
            return self._db
        try:
            import lancedb
        except ImportError as exc:
            raise RuntimeError("lancedb is not installed") from exc
        self.config.lance_dir.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.config.lance_dir))
        return self._db

    def _get_or_create_table(self):
        """Get the documents table, creating it if needed."""
        if self._table is not None:
            return self._table
        db = self._connect()
        table_name = self.config.table_name
        try:
            self._table = db.open_table(table_name)
        except Exception:
            # Table doesn't exist yet — create with full metadata schema
            import pyarrow as pa
            schema = pa.schema([
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("source", pa.string()),
                pa.field("source_type", pa.string()),
                pa.field("heading", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("embedded_at", pa.float64()),
                pa.field("vector", pa.list_(pa.float32(), self.config.embedding_dims)),
                # Metadata fields for filtering and citation
                pa.field("doc_id", pa.string()),
                pa.field("title", pa.string()),
                pa.field("domain", pa.string()),
                pa.field("content_format", pa.string()),
                pa.field("topic", pa.string()),
                pa.field("status", pa.string()),
                pa.field("language", pa.string()),
                pa.field("tags", pa.string()),
                pa.field("keywords", pa.string()),
                pa.field("content_hash", pa.string()),
                pa.field("chunk_strategy", pa.string()),
            ])
            self._table = db.create_table(table_name, schema=schema, mode="overwrite")
            logger.info("Created LanceDB table '%s' with %d-dim vectors", table_name, self.config.embedding_dims)
        return self._table

    def get_existing_sources(self) -> set[str]:
        """Return the set of source paths already in the store."""
        table = self._get_or_create_table()
        try:
            df = table.to_pandas()
            return set(df["source"].unique().tolist())
        except Exception:
            return set()

    def ingest(
        self,
        text: str,
        source: str,
        source_type: str = "text",
        heading: str = "",
    ) -> int:
        """Chunk, embed, and store a document. Returns chunk count."""
        chunks = chunk_text(
            text,
            source_type=source_type,
            max_chars=self.config.chunk_max_chars,
            overlap=self.config.chunk_overlap_chars,
        )
        if not chunks:
            return 0

        # Embed all chunks
        try:
            vectors = self.embedder.embed([c.text for c in chunks])
        except EmbeddingError as exc:
            logger.error("Embedding failed for %s: %s", source, exc)
            return 0

        # Build records
        now = time.time()
        records = []
        for chunk, vec in zip(chunks, vectors):
            records.append({
                "id": f"{source}#{chunk.index}",
                "text": chunk.text,
                "source": source,
                "source_type": source_type,
                "heading": chunk.heading or heading,
                "chunk_index": chunk.index,
                "embedded_at": now,
                "vector": vec,
            })

        table = self._get_or_create_table()
        table.add(records)
        logger.info("Ingested %d chunks from %s", len(records), source)
        return len(records)

    def ingest_with_metadata(self, records: list[dict]) -> int:
        """Ingest pre-built records with full metadata. Returns chunk count.
        
        Each record must include: text, source, source_type, heading, chunk_index,
        vector, and all metadata fields (doc_id, title, domain, etc.)
        """
        if not records:
            return 0
        table = self._get_or_create_table()
        table.add(records)
        logger.info("Ingested %d chunks with metadata", len(records))
        return len(records)

    def vector_search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """Pure semantic vector search."""
        try:
            query_vec = self.embedder.embed_one(query)
        except EmbeddingError as exc:
            logger.error("Query embedding failed: %s", exc)
            return []
        if not query_vec:
            return []
        table = self._get_or_create_table()
        try:
            results = table.search(query_vec).limit(top_k).to_list()
        except Exception as exc:
            logger.error("Vector search failed: %s", exc)
            return []
        return [
            SearchResult(
                text=r.get("text", ""),
                source=r.get("source", ""),
                source_type=r.get("source_type", ""),
                heading=r.get("heading", ""),
                score=1.0 - r.get("_distance", 1.0),
                chunk_index=r.get("chunk_index", 0),
                title=r.get("title", ""),
                domain=r.get("domain", ""),
                tags=r.get("tags", ""),
                keywords=r.get("keywords", ""),
                doc_id=r.get("doc_id", ""),
                content_format=r.get("content_format", ""),
            )
            for r in results
        ]

    def keyword_search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """Full-text keyword search using LanceDB's FTS."""
        table = self._get_or_create_table()
        try:
            results = table.search(query, query_type="fts").limit(top_k).to_list()
        except Exception as exc:
            logger.debug("FTS search failed (may not be indexed yet): %s", exc)
            return []
        return [
            SearchResult(
                text=r.get("text", ""),
                source=r.get("source", ""),
                source_type=r.get("source_type", ""),
                heading=r.get("heading", ""),
                score=r.get("_score", 0.0),
                chunk_index=r.get("chunk_index", 0),
            )
            for r in results
        ]

    def hybrid_search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """Hybrid search combining vector + keyword results via RRF."""
        vec_results = self.vector_search(query, top_k=top_k * 2)
        kw_results = self.keyword_search(query, top_k=top_k * 2)

        if not vec_results and not kw_results:
            return []
        if not vec_results:
            return kw_results[:top_k]
        if not kw_results:
            return vec_results[:top_k]

        # Reciprocal Rank Fusion
        scores: dict[str, float] = {}
        metadata: dict[str, SearchResult] = {}
        for rank, r in enumerate(vec_results):
            key = f"{r.source}#{r.chunk_index}"
            scores[key] = scores.get(key, 0) + 1.0 / (rank + 1)
            metadata[key] = r
        for rank, r in enumerate(kw_results):
            key = f"{r.source}#{r.chunk_index}"
            scores[key] = scores.get(key, 0) + 1.0 / (rank + 1)
            if key not in metadata:
                metadata[key] = r

        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return [metadata[k] for k, _ in ranked[:top_k]]

    def remove_source(self, source: str) -> int:
        """Remove all chunks from a given source. Returns removed count."""
        table = self._get_or_create_table()
        try:
            table.delete(f'source = "{source}"')
            logger.info("Removed source: %s", source)
            return 1
        except Exception as exc:
            logger.error("Remove failed for %s: %s", source, exc)
            return 0

    def status(self) -> dict[str, Any]:
        """Return store statistics."""
        try:
            table = self._get_or_create_table()
            count = table.count_rows()
            return {
                "available": True,
                "chunk_count": count,
                "embedding_model": self.config.embedding_model,
                "embedding_dims": self.config.embedding_dims,
                "lance_dir": str(self.config.lance_dir),
                "table_name": self.config.table_name,
            }
        except Exception as exc:
            return {
                "available": False,
                "error": str(exc),
                "chunk_count": 0,
                "embedding_model": self.config.embedding_model,
            }