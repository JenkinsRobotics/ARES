"""Web page ingestion pipeline — extract text from URLs and ingest."""

from __future__ import annotations

import logging
import re
import urllib.request
from typing import Any

from ..config import KBConfig
from ..vector.store import KnowledgeStore

logger = logging.getLogger(__name__)


def _strip_html(html: str) -> str:
    """Basic HTML to text conversion without external deps."""
    # Remove script and style content
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Decode common entities
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&#39;', "'").replace('&quot;', '"')
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_title(html: str) -> str:
    match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def ingest_url(url: str, config: KBConfig, store: KnowledgeStore | None = None) -> dict:
    """Fetch a web page, extract text, and ingest it into the vector store."""
    if store is None:
        store = KnowledgeStore(config)

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ARES-KB/1.0"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(500_000)  # 500KB max
            html = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": f"Failed to fetch URL: {exc}"}

    if "html" not in content_type and "<html" not in html.lower():
        # Not HTML — treat as plain text
        text = html
        title = url
    else:
        text = _strip_html(html)
        title = _extract_title(html) or url

    if not text.strip():
        return {"ok": False, "error": "No text extracted from URL"}

    source = url
    chunks = store.ingest(text, source=source, source_type="web", heading=title)
    return {"ok": True, "chunks_created": chunks, "source": source, "title": title, "chars_extracted": len(text)}