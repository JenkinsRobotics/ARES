"""Graph construction pipeline — chunk → extract → merge → store.

Builds the knowledge graph from documents in the vector store.
Can be triggered after ingestion or run as a batch job over all sources.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import KBConfig
from ..vector.store import KnowledgeStore
from .extractor import extract
from .store import GraphStore

logger = logging.getLogger(__name__)


def build_graph_from_source(
    source: str,
    config: KBConfig,
    vector_store: KnowledgeStore | None = None,
    graph_store: GraphStore | None = None,
) -> dict[str, Any]:
    """Extract entities and relationships from all chunks of a given source.

    Reads chunks from the vector store, extracts entities/relationships,
    and adds them to the graph store.
    """
    if vector_store is None:
        vector_store = KnowledgeStore(config)
    if graph_store is None:
        graph_store = GraphStore(config)

    # Get all chunks for this source
    table = vector_store._get_or_create_table()
    try:
        # LanceDB API: use search().to_list() or table.to_pandas()
        try:
            all_data = table.to_pandas()
        except Exception:
            try:
                all_data = table.search().limit(10000).to_list()
            except Exception:
                all_data = []
        chunks = [row for row in (all_data.to_dict('records') if hasattr(all_data, 'to_dict') else all_data) if row.get("source") == source]
    except Exception as exc:
        logger.error("Failed to read chunks for %s: %s", source, exc)
        return {"ok": False, "error": str(exc)}

    if not chunks:
        return {"ok": False, "error": "No chunks found for source"}

    total_entities = 0
    total_relationships = 0

    for chunk in chunks:
        text = chunk.get("text", "")
        if not text:
            continue
        result = extract(text, source, config)
        added = graph_store.add_extraction(result)
        total_entities += len(result.entities)
        total_relationships += len(result.relationships)

    return {
        "ok": True,
        "source": source,
        "chunks_processed": len(chunks),
        "entities_extracted": total_entities,
        "relationships_extracted": total_relationships,
    }


def build_graph_all(config: KBConfig) -> dict[str, Any]:
    """Build the graph from all sources in the vector store."""
    vector_store = KnowledgeStore(config)
    graph_store = GraphStore(config)

    # Get all unique sources
    table = vector_store._get_or_create_table()
    try:
        try:
            all_chunks = table.to_pandas()
            all_chunks = all_chunks.to_dict('records')
        except Exception:
            all_chunks = table.search().limit(10000).to_list()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    sources = set(c.get("source", "") for c in all_chunks if c.get("source"))
    if not sources:
        return {"ok": False, "error": "No sources in vector store"}

    results = []
    total_entities = 0
    total_relationships = 0

    for source in sources:
        result = build_graph_from_source(source, config, vector_store, graph_store)
        results.append(result)
        if result.get("ok"):
            total_entities += result.get("entities_extracted", 0)
            total_relationships += result.get("relationships_extracted", 0)

    return {
        "ok": True,
        "sources_processed": len(sources),
        "total_entities": total_entities,
        "total_relationships": total_relationships,
        "details": results,
    }