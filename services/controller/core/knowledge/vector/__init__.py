"""LanceDB vector store — hybrid BM25 + vector search."""

from .store import KnowledgeStore
from .chunker import chunk_text, chunk_markdown, TextChunk
from .embedder import Embedder

__all__ = ["KnowledgeStore", "chunk_text", "chunk_markdown", "TextChunk", "Embedder"]