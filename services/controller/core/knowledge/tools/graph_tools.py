"""GraphRAG MCP tools — kb_graph_query, kb_graph_status, kb_graph_build."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def register_graph_tools(
    mcp: Any,
    require_fn: Callable[[str], dict],
    audit_fn: Callable[..., None],
    resolve_fn: Callable[..., Any],
) -> None:

    @mcp.tool()
    def kb_graph_query(
        query: str,
        depth: int = 2,
        mode: str = "local",
    ) -> dict:
        """Query the knowledge graph for multi-hop reasoning.

        Args:
            query: Natural language query about entity relationships
            depth: Graph traversal depth (1-4)
            mode: local (entity-centric), global (community summaries), drift (hybrid)

        Returns:
            Dict with matched entities, paths, and edge evidence.
        """
        require_fn("kb.graph.query")
        from ..config import KBConfig
        from ..graph.store import GraphStore

        config = KBConfig.from_env()
        store = GraphStore(config)
        result = store.query(query, depth=depth, mode=mode)
        audit_fn("kb.graph.query", outcome="allowed", query=query[:200])
        return result

    @mcp.tool()
    def kb_graph_status() -> dict:
        """Return knowledge graph statistics: entity count, relationship count, communities."""
        require_fn("kb.graph.status")
        from ..config import KBConfig
        from ..graph.store import GraphStore

        config = KBConfig.from_env()
        store = GraphStore(config)
        status = store.status()
        audit_fn("kb.graph.status", outcome="allowed")
        return status

    @mcp.tool()
    def kb_graph_build(source: str = "") -> dict:
        """Build the knowledge graph from ingested documents.

        Args:
            source: Specific source to process. Empty = process all sources.

        Returns:
            Dict with entities and relationships extracted.
        """
        require_fn("kb.graph.query")
        from ..config import KBConfig
        from ..graph.builder import build_graph_from_source, build_graph_all

        config = KBConfig.from_env()
        if source:
            result = build_graph_from_source(source, config)
        else:
            result = build_graph_all(config)
        audit_fn("kb.graph.build", outcome="allowed", source=source[:200])
        return result