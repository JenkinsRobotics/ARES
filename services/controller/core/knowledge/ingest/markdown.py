"""Markdown/plain text ingestion pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..config import KBConfig
from ..vector.store import KnowledgeStore

logger = logging.getLogger(__name__)


def ingest_file(file_path: str, config: KBConfig, store: KnowledgeStore | None = None) -> dict:
    """Read a text/markdown file and ingest it into the vector store."""
    if store is None:
        store = KnowledgeStore(config)

    path = Path(file_path)
    if not path.exists():
        return {"ok": False, "error": f"File not found: {file_path}"}

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": f"Failed to read file: {exc}"}

    if not text.strip():
        return {"ok": False, "error": "File is empty"}

    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown"):
        source_type = "markdown"
    elif suffix in (".txt", ".text"):
        source_type = "text"
    else:
        source_type = "text"

    source = str(path)
    chunks = store.ingest(text, source=source, source_type=source_type, heading=path.stem)
    return {"ok": True, "chunks_created": chunks, "source": source, "chars_extracted": len(text)}


def ingest_directory(dir_path: str, config: KBConfig, store: KnowledgeStore | None = None) -> dict:
    """Ingest all text/markdown files in a directory."""
    if store is None:
        store = KnowledgeStore(config)

    path = Path(dir_path)
    if not path.is_dir():
        return {"ok": False, "error": f"Not a directory: {dir_path}"}

    results = []
    total_chunks = 0
    extensions = {".md", ".markdown", ".txt", ".text", ".rst"}

    for file_path in sorted(path.rglob("*")):
        if file_path.suffix.lower() in extensions and file_path.is_file():
            result = ingest_file(str(file_path), config, store)
            results.append({"file": str(file_path), "ok": result.get("ok", False), "chunks": result.get("chunks_created", 0)})
            if result.get("ok"):
                total_chunks += result.get("chunks_created", 0)

    return {
        "ok": True,
        "files_processed": len(results),
        "total_chunks": total_chunks,
        "details": results[:50],
    }