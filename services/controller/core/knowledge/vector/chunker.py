"""Content-aware chunking for the knowledge base.

Splits documents into meaningful pieces for embedding.
Handles markdown, plain text, transcripts, and structured content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class TextChunk:
    text: str
    index: int
    heading: str
    source_type: str = "text"


_HEADING_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)
_SENTENCE_END_RE = re.compile(r"[.!?]\s+")


def _split_paragraphs(block: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", block) if p.strip()]


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) pairs."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", text)]
    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        sections.append(("", text[: matches[0].start()]))
    for i, match in enumerate(matches):
        heading = match.group().strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((heading, text[body_start:body_end]))
    return sections


def chunk_markdown(text: str, *, max_chars: int = 1200, overlap: int = 150) -> list[TextChunk]:
    """Chunk markdown on heading/paragraph boundaries with heading context."""
    if not text or not text.strip():
        return []
    chunks: list[TextChunk] = []
    idx = 0
    for heading, body in _split_sections(text):
        paragraphs = _split_paragraphs(body)
        if not paragraphs:
            if heading:
                chunks.append(TextChunk(text=heading, index=idx, heading=heading, source_type="markdown"))
                idx += 1
            continue
        current = heading
        carry = ""
        for para in paragraphs:
            candidate = f"{current}\n\n{para}" if current else para
            if current and current != heading and len(candidate) > max_chars:
                chunks.append(TextChunk(text=current, index=idx, heading=heading, source_type="markdown"))
                idx += 1
                last_para = current.split("\n\n")[-1]
                carry = last_para[-overlap:] if len(last_para) > overlap else last_para
                current = f"{heading}\n\n{carry}\n\n{para}" if heading else f"{carry}\n\n{para}"
            else:
                current = candidate
        if current:
            chunks.append(TextChunk(text=current, index=idx, heading=heading, source_type="markdown"))
            idx += 1
    return chunks


def chunk_plain(text: str, *, max_chars: int = 1200, overlap: int = 150) -> list[TextChunk]:
    """Chunk plain text on paragraph boundaries."""
    if not text or not text.strip():
        return []
    paragraphs = _split_paragraphs(text)
    chunks: list[TextChunk] = []
    idx = 0
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > max_chars and current:
            chunks.append(TextChunk(text=current, index=idx, heading="", source_type="text"))
            idx += 1
            carry = current[-overlap:] if len(current) > overlap else current
            current = f"{carry}\n\n{para}"
        else:
            current = candidate
    if current:
        chunks.append(TextChunk(text=current, index=idx, heading="", source_type="text"))
        idx += 1
    return chunks


def chunk_transcript(text: str, *, max_chars: int = 1200, overlap: int = 100) -> list[TextChunk]:
    """Chunk a transcript by timestamp/speaker segments."""
    if not text or not text.strip():
        return []
    # Try to split on common transcript patterns
    segments = re.split(r"(\[\d+:\d+\]|\d+:\d+:\d+|Speaker \d+:)", text)
    chunks: list[TextChunk] = []
    idx = 0
    current = ""
    for seg in segments:
        if not seg.strip():
            continue
        candidate = f"{current}\n{seg}" if current else seg
        if len(candidate) > max_chars and current:
            chunks.append(TextChunk(text=current, index=idx, heading="transcript", source_type="transcript"))
            idx += 1
            current = seg
        else:
            current = candidate
    if current:
        chunks.append(TextChunk(text=current, index=idx, heading="transcript", source_type="transcript"))
        idx += 1
    return chunks


def chunk_text(text: str, source_type: str = "text", *, max_chars: int = 1200, overlap: int = 150) -> list[TextChunk]:
    """Auto-dispatch to the right chunker based on source type."""
    if source_type in ("markdown", "md", "note"):
        return chunk_markdown(text, max_chars=max_chars, overlap=overlap)
    elif source_type in ("transcript", "youtube"):
        return chunk_transcript(text, max_chars=max_chars, overlap=overlap)
    else:
        return chunk_plain(text, max_chars=max_chars, overlap=overlap)