"""Ingestion pipeline orchestrator.

Routes different source types to the right ingestion pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import KBConfig
from ..vector.store import KnowledgeStore
from .pdf import ingest_pdf
from .web import ingest_url
from .youtube import ingest_youtube
from .markdown import ingest_file, ingest_directory

logger = logging.getLogger(__name__)


def ingest(source: str, config: KBConfig, store: KnowledgeStore | None = None) -> dict:
    """Auto-detect source type and route to the right pipeline.

    Args:
        source: URL, file path, or directory path
        config: KB config
        store: Optional pre-existing KnowledgeStore

    Returns:
        Dict with ok status, chunks_created, and source info.
    """
    if store is None:
        store = KnowledgeStore(config)

    # YouTube URL
    if "youtube.com" in source or "youtu.be" in source:
        return ingest_youtube(source, config, store)

    # Web URL (http/https, not local file)
    if source.startswith("http://") or source.startswith("https://"):
        if "youtube.com" not in source and "youtu.be" not in source:
            return ingest_url(source, config, store)

    # PDF file
    if source.lower().endswith(".pdf"):
        return ingest_pdf(source, config, store)

    # Directory
    from pathlib import Path
    p = Path(source)
    if p.is_dir():
        return ingest_directory(source, config, store)

    # Markdown/text file
    if p.is_file():
        return ingest_file(source, config, store)

    return {"ok": False, "error": f"Could not determine source type for: {source}"}