"""Vector RAG MCP tools — kb_query, kb_ingest, kb_status, kb_remove."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def register_vector_tools(
    mcp: Any,
    require_fn: Callable[[str], dict],
    audit_fn: Callable[..., None],
    resolve_fn: Callable[..., Any],
) -> None:

    @mcp.tool()
    def kb_query(
        query: str,
        top_k: int = 10,
        source_type: str = "",
        hybrid: bool = True,
    ) -> dict:
        """Search the knowledge base. Uses hybrid (vector + keyword) search by default.

        Args:
            query: Natural language query
            top_k: Number of results to return
            source_type: Filter by source type (paper, transcript, web, note, text). Empty = all.
            hybrid: Use hybrid search (vector + BM25 fusion). Set False for vector-only.

        Returns:
            Dict with results list and total_found count.
        """
        require_fn("kb.query")
        from ..config import KBConfig
        from ..vector.store import KnowledgeStore

        config = KBConfig.from_env()
        store = KnowledgeStore(config)

        if hybrid:
            results = store.hybrid_search(query, top_k=top_k)
        else:
            results = store.vector_search(query, top_k=top_k)

        if source_type:
            results = [r for r in results if r.source_type == source_type]

        audit_fn("kb.query", outcome="allowed", query=query[:200])
        return {
            "results": [
                {
                    "text": r.text,
                    "source": r.source,
                    "source_type": r.source_type,
                    "heading": r.heading,
                    "score": round(r.score, 4),
                    "chunk_index": r.chunk_index,
                }
                for r in results
            ],
            "total_found": len(results),
        }

    @mcp.tool()
    def kb_ingest(
        source: str,
        text: str = "",
        source_type: str = "",
        title: str = "",
    ) -> dict:
        """Ingest a document into the knowledge base.

        Auto-detects source type: YouTube URLs fetch transcripts, web URLs extract
        page content, PDFs extract text, directories batch-process all text files.
        If raw text is provided directly, it's ingested as-is.

        Args:
            source: URL, file path, or directory path. If text is provided, this is the source identifier.
            text: Raw text to ingest. If empty, the source is fetched/read automatically.
            source_type: Override type detection (paper, transcript, web, note, markdown, text). Empty = auto-detect.
            title: Optional title for the document

        Returns:
            Dict with ok status, chunks_created count, and source info.
        """
        require_fn("kb.ingest")
        from ..config import KBConfig
        from ..vector.store import KnowledgeStore

        config = KBConfig.from_env()
        store = KnowledgeStore(config)

        # If text is provided directly, ingest it
        if text:
            st = source_type or "text"
            chunks = store.ingest(text, source=source, source_type=st, heading=title)
            audit_fn("kb.ingest", outcome="allowed", source=source[:200], chunks=chunks)
            return {"ok": True, "chunks_created": chunks, "source": source}

        # Auto-detect and route
        from ..ingest.pipeline import ingest as auto_ingest
        result = auto_ingest(source, config, store)
        audit_fn("kb.ingest", outcome="allowed", source=source[:200])
        return result

    @mcp.tool()
    def kb_status() -> dict:
        """Return knowledge base statistics: chunk count, sources, embedding model, health."""
        require_fn("kb.status")
        from ..config import KBConfig
        from ..vector.store import KnowledgeStore

        config = KBConfig.from_env()
        store = KnowledgeStore(config)
        status = store.status()
        audit_fn("kb.status", outcome="allowed")
        return status

    @mcp.tool()
    def kb_remove(source: str) -> dict:
        """Remove all chunks from a given source.

        Args:
            source: The source identifier to remove

        Returns:
            Dict with ok status.
        """
        require_fn("kb.remove")
        from ..config import KBConfig
        from ..vector.store import KnowledgeStore

        config = KBConfig.from_env()
        store = KnowledgeStore(config)
        removed = store.remove_source(source)
        audit_fn("kb.remove", outcome="allowed", source=source[:200])
        return {"ok": removed > 0, "source": source}