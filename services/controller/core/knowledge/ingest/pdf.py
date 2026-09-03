"""PDF ingestion pipeline — extract text from PDFs and ingest into the vector store."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..config import KBConfig
from ..vector.store import KnowledgeStore

logger = logging.getLogger(__name__)


def ingest_pdf(pdf_path: str, config: KBConfig, store: KnowledgeStore | None = None) -> dict:
    """Extract text from a PDF and ingest it into the vector store."""
    if store is None:
        store = KnowledgeStore(config)

    path = Path(pdf_path)
    if not path.exists():
        return {"ok": False, "error": f"File not found: {pdf_path}"}

    # Try PyMuPDF first (fastest, most reliable)
    text = ""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        for page in doc:
            text += page.get_text() + "\n\n"
        doc.close()
    except ImportError:
        logger.info("PyMuPDF not available, trying alternatives")
        try:
            # Try pdfminer
            from pdfminer.high_level import extract_text
            text = extract_text(str(path))
        except ImportError:
            logger.warning("No PDF library available (install PyMuPDF or pdfminer)")
            return {"ok": False, "error": "No PDF library installed. Run: pip install PyMuPDF"}

    if not text.strip():
        return {"ok": False, "error": "No text extracted from PDF (may be scanned images)"}

    source = str(path)
    chunks = store.ingest(text, source=source, source_type="paper", heading=path.stem)
    return {"ok": True, "chunks_created": chunks, "source": source, "chars_extracted": len(text)}