"""
Alexandria Knowledge Base — Metadata Schema and Standards

This module defines the metadata schema for every document ingested into the KB.
Based on industry best practices from Microsoft Azure RAG guidance, Amazon Bedrock,
and production RAG systems (LlamaIndex, LangChain, RAGFlow).

Design principle: "Facts live in text; routing signals live in metadata."
- Metadata enables filtering, ranking, and citation
- Text contains the actual knowledge
- Every chunk must trace to exactly one source document

SCHEMA LAYERS:
1. Document-level: identity, provenance, classification, lifecycle
2. Chunk-level: position, context, enrichment (summary, keywords, entities)
3. Access/control: who can retrieve, freshness windows
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import hashlib
import os
from datetime import datetime


class ContentDomain(str, Enum):
    """Controlled vocabulary for domain classification."""
    ENGINEERING = "engineering"       # Robotics, code, hardware, firmware
    BUSINESS = "business"             # Contracts, finance, operations, admin
    RESEARCH = "research"             # Papers, studies, analysis, literature
    KNOWLEDGE = "knowledge"           # Reference material, guides, documentation
    OPERATIONS = "operations"         # Runbooks, procedures, system configs
    CREATIVE = "creative"             # Content, scripts, marketing, media
    ARCHIVE = "archive"               # Historical, deprecated, legacy
    SYSTEM = "system"                 # System files, configs, infrastructure


class ContentFormat(str, Enum):
    """File format classification for chunking strategy selection."""
    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"
    CODE = "code"
    JSON = "json"
    YAML = "yaml"
    HTML = "html"
    CSV = "csv"
    PDF = "pdf"
    IMAGE = "image"                   # Requires vision model
    TRANSCRIPT = "transcript"         # Video/audio transcripts
    UNKNOWN = "unknown"


class LifecycleStatus(str, Enum):
    """Document lifecycle state."""
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"


class ChunkStrategy(str, Enum):
    """Chunking strategy — chosen per content type."""
    RECURSIVE = "recursive"           # Safe default: paragraph boundaries
    SEMANTIC = "semantic"             # Embedding-based topic boundaries
    HIERARCHICAL = "hierarchical"     # Heading-structured (markdown, specs)
    FIXED = "fixed"                   # Token-count based (code, logs)
    SENTENCE_WINDOW = "sentence_window"  # Q&A, chat logs


# Controlled vocabulary for tags — derived from Matthew's actual content domains
# Keep to ~30-40 canonical tags. Too many = noise. Too few = no filtering.
CANONICAL_TAGS = {
    # Engineering
    "robotics", "firmware", "hardware", "python", "javascript", "typescript",
    "swift", "cpp", "rust", "go", "3d-printing", "cad", "electronics",
    "pcb", "sensor", "actuator", "motor-control", "realtime",
    # Business
    "contract", "finance", "invoice", "proposal", "grant", "report",
    "budget", "compliance", "legal",
    # Research
    "paper", "study", "experiment", "dataset", "benchmark", "survey",
    "literature-review", "thesis",
    # Knowledge
    "guide", "tutorial", "reference", "documentation", "faq", "glossary",
    "best-practices", "architecture", "design",
    # Operations
    "runbook", "config", "deployment", "monitoring", "security",
    "backup", "network", "database",
    # Creative
    "video", "script", "transcript", "thumbnail", "marketing",
    # Meta
    "index", "template", "todo", "meeting-notes", "journal",
}


@dataclass
class DocumentMetadata:
    """Document-level metadata — applies to every chunk from this document."""
    # Identity
    doc_id: str                       # Stable hash of source path
    title: str                        # Extracted or filename-derived
    source_path: str                  # Full path on NAS
    source_type: str                  # "nas", "web", "youtube", "manual"

    # Classification
    domain: str                       # ContentDomain value
    content_format: str               # ContentFormat value
    topic: str = ""                   # Sub-topic within domain (e.g. "JP01-robot")
    subtopic: str = ""                # Further refinement

    # Provenance
    author: str = ""                  # If detectable from content
    created_date: str = ""            # ISO date if detectable
    modified_date: str = ""           # File mtime
    ingested_date: str = ""           # When this was added to KB

    # Lifecycle
    status: str = "active"            # LifecycleStatus value
    version: str = ""                 # If versioned
    owner: str = ""                   # Responsible party

    # Content metrics
    file_size: int = 0
    content_hash: str = ""            # SHA-256 of content for dedup
    language: str = "en"              # Detected language
    char_count: int = 0
    line_count: int = 0

    # Enrichment (populated during ingestion)
    tags: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    summary: str = ""                 # LLM-generated 1-2 sentence summary
    entities: list[str] = field(default_factory=list)  # Named entities

    # Chunking
    chunk_strategy: str = "recursive"
    chunk_count: int = 0


@dataclass
class ChunkMetadata:
    """Chunk-level metadata — attached to each individual chunk."""
    chunk_id: str                     # "{doc_id}#{index}"
    doc_id: str                       # Parent document ID
    chunk_index: int                  # Position within document
    heading_path: list[str] = field(default_factory=list)  # ["Section", "Subsection"]
    chunk_summary: str = ""           # Brief context for this specific chunk
    chunk_tags: list[str] = field(default_factory=list)     # Inherited + chunk-specific
    position_type: str = "body"       # "title", "heading", "body", "code", "table"


def compute_doc_id(source_path: str) -> str:
    """Stable document ID from source path."""
    return hashlib.sha256(source_path.encode()).hexdigest()[:16]


def compute_content_hash(content: str) -> str:
    """SHA-256 hash of content for dedup and change detection."""
    return hashlib.sha256(content.encode()).hexdigest()


def detect_content_format(filepath: str) -> str:
    """Detect content format from file extension."""
    ext = os.path.splitext(filepath)[1].lower().lstrip(".")
    format_map = {
        "md": ContentFormat.MARKDOWN,
        "markdown": ContentFormat.MARKDOWN,
        "txt": ContentFormat.PLAIN_TEXT,
        "py": ContentFormat.CODE,
        "js": ContentFormat.CODE,
        "ts": ContentFormat.CODE,
        "jsx": ContentFormat.CODE,
        "tsx": ContentFormat.CODE,
        "sh": ContentFormat.CODE,
        "bash": ContentFormat.CODE,
        "sql": ContentFormat.CODE,
        "c": ContentFormat.CODE,
        "cpp": ContentFormat.CODE,
        "h": ContentFormat.CODE,
        "hpp": ContentFormat.CODE,
        "rs": ContentFormat.CODE,
        "go": ContentFormat.CODE,
        "java": ContentFormat.CODE,
        "rb": ContentFormat.CODE,
        "php": ContentFormat.CODE,
        "swift": ContentFormat.CODE,
        "dart": ContentFormat.CODE,
        "kt": ContentFormat.CODE,
        "scala": ContentFormat.CODE,
        "lua": ContentFormat.CODE,
        "r": ContentFormat.CODE,
        "json": ContentFormat.JSON,
        "yaml": ContentFormat.YAML,
        "yml": ContentFormat.YAML,
        "toml": ContentFormat.YAML,
        "ini": ContentFormat.YAML,
        "cfg": ContentFormat.YAML,
        "html": ContentFormat.HTML,
        "htm": ContentFormat.HTML,
        "csv": ContentFormat.CSV,
        "xml": ContentFormat.HTML,
        "srt": ContentFormat.TRANSCRIPT,
        "vtt": ContentFormat.TRANSCRIPT,
        "pdf": ContentFormat.PDF,
        "png": ContentFormat.IMAGE,
        "jpg": ContentFormat.IMAGE,
        "jpeg": ContentFormat.IMAGE,
        "webp": ContentFormat.IMAGE,
        "gif": ContentFormat.IMAGE,
    }
    return format_map.get(ext, ContentFormat.UNKNOWN).value


def detect_domain(filepath: str, content: str = "") -> str:
    """Detect content domain from path and content."""
    path_lower = filepath.lower()
    parts = path_lower.split("/")

    # Path-based detection
    if any(x in path_lower for x in ["03_knowledge", "05_research", "research_library"]):
        if "research" in path_lower or "paper" in path_lower or "study" in path_lower:
            return ContentDomain.RESEARCH.value
        return ContentDomain.KNOWLEDGE.value
    if any(x in path_lower for x in ["01_business", "business", "contract", "invoice", "finance"]):
        return ContentDomain.BUSINESS.value
    if any(x in path_lower for x in ["02_projects", "projects", "ares-projects"]):
        if any(x in path_lower for x in ["robot", "firmware", "hardware", "pcb", "cad"]):
            return ContentDomain.ENGINEERING.value
        return ContentDomain.ENGINEERING.value
    if any(x in path_lower for x in ["04_content", "content", "video", "script", "transcript"]):
        return ContentDomain.CREATIVE.value
    if any(x in path_lower for x in ["00_system", "system", "config", "06_agents", "agents"]):
        return ContentDomain.SYSTEM.value
    if any(x in path_lower for x in ["08_reports", "reports", "09_archive", "archive"]):
        return ContentDomain.ARCHIVE.value
    if any(x in path_lower for x in ["07_intake", "intake"]):
        # Intake is mixed — try to classify by content
        if content:
            content_lower = content[:2000].lower()
            if any(x in content_lower for x in ["abstract", "doi", "references", "et al"]):
                return ContentDomain.RESEARCH.value
            if any(x in content_lower for x in ["contract", "agreement", "party", "whereas"]):
                return ContentDomain.BUSINESS.value
            if any(x in content_lower for x in ["def ", "import ", "class ", "function "]):
                return ContentDomain.ENGINEERING.value
            if any(x in content_lower for x in ["guide", "tutorial", "how to", "setup"]):
                return ContentDomain.KNOWLEDGE.value
        return ContentDomain.KNOWLEDGE.value  # Default for intake

    return ContentDomain.KNOWLEDGE.value


def choose_chunk_strategy(content_format: str, content: str = "") -> str:
    """Choose chunking strategy based on content type."""
    if content_format == ContentFormat.MARKDOWN.value:
        return ChunkStrategy.HIERARCHICAL.value
    if content_format == ContentFormat.CODE.value:
        return ChunkStrategy.FIXED.value
    if content_format == ContentFormat.TRANSCRIPT.value:
        return ChunkStrategy.SENTENCE_WINDOW.value
    if content_format == ContentFormat.JSON.value:
        return ChunkStrategy.FIXED.value
    if content_format == ContentFormat.CSV.value:
        return ChunkStrategy.FIXED.value
    if content_format == ContentFormat.HTML.value:
        return ChunkStrategy.HIERARCHICAL.value
    return ChunkStrategy.RECURSIVE.value


def extract_title(content: str, filepath: str) -> str:
    """Extract document title from content or filename."""
    if content:
        # Try first H1 heading in markdown
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                return stripped[2:].strip()[:200]
        # Try first non-empty line
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped[:200]
    # Fall back to filename
    return os.path.basename(filepath)


def detect_tags(filepath: str, content: str) -> list[str]:
    """Auto-tag document based on path and content against controlled vocabulary."""
    found_tags = set()
    combined = (filepath + " " + content[:5000]).lower()

    for tag in CANONICAL_TAGS:
        if tag.replace("-", " ") in combined or tag in combined:
            found_tags.add(tag)

    # Limit to most relevant (max 8 tags per doc to avoid noise)
    return sorted(list(found_tags))[:8]


def extract_keywords(content: str, max_keywords: int = 10) -> list[str]:
    """Extract keywords using simple frequency analysis.
    
    This is a lightweight NLP-free approach. For better results,
    could use KeyBERT or RAKE, but those add dependencies.
    """
    import re
    # Remove common stop words
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "by", "from", "is", "was", "are", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "must", "can",
        "this", "that", "these", "those", "i", "you", "he", "she", "it",
        "we", "they", "what", "which", "who", "when", "where", "why", "how",
        "all", "each", "every", "both", "few", "more", "most", "other",
        "some", "such", "no", "not", "only", "own", "same", "so", "than",
        "too", "very", "just", "also", "here", "there", "now", "then",
        "if", "else", "while", "return", "import", "from", "class", "def",
        "true", "false", "none", "null", "void", "int", "str", "list",
        "self", "this", "data", "value", "name", "type", "file", "line",
        "use", "using", "used", "set", "get", "new", "one", "two",
    }

    # Extract words
    words = re.findall(r'\b[a-zA-Z][a-zA-Z0-9_-]{2,30}\b', content[:10000].lower())
    
    # Count frequency (excluding stop words)
    freq = {}
    for word in words:
        if word not in stop_words and len(word) > 2:
            freq[word] = freq.get(word, 0) + 1

    # Return top keywords
    sorted_keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [k for k, v in sorted_keywords[:max_keywords]]


def build_document_metadata(
    filepath: str,
    content: str,
    source_type: str = "nas",
) -> DocumentMetadata:
    """Build complete document metadata for a file."""
    doc_id = compute_doc_id(filepath)
    content_format = detect_content_format(filepath)
    domain = detect_domain(filepath, content)
    chunk_strategy = choose_chunk_strategy(content_format, content)
    title = extract_title(content, filepath)
    tags = detect_tags(filepath, content)
    keywords = extract_keywords(content)
    content_hash = compute_content_hash(content)

    # File stats
    try:
        stat = os.stat(filepath)
        file_size = stat.st_size
        modified_date = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except Exception:
        file_size = len(content.encode())
        modified_date = ""

    return DocumentMetadata(
        doc_id=doc_id,
        title=title,
        source_path=filepath,
        source_type=source_type,
        domain=domain,
        content_format=content_format,
        chunk_strategy=chunk_strategy,
        tags=tags,
        keywords=keywords,
        content_hash=content_hash,
        file_size=file_size,
        modified_date=modified_date,
        ingested_date=datetime.now().isoformat(),
        char_count=len(content),
        line_count=content.count("\n") + 1,
        language="en",  # TODO: detect language
    )


def build_chunk_metadata(
    doc_meta: DocumentMetadata,
    chunk_index: int,
    chunk_text: str,
    heading: str = "",
) -> tuple[dict, dict]:
    """Build chunk-level metadata and the LanceDB record.

    Returns (chunk_metadata_dict, lancedb_record_dict) ready for insertion.
    """
    chunk_id = f"{doc_meta.doc_id}#{chunk_index}"

    # Heading path — split by " > " if hierarchical
    heading_path = [h.strip() for h in heading.split(" > ") if h.strip()] if heading else []

    chunk_meta = ChunkMetadata(
        chunk_id=chunk_id,
        doc_id=doc_meta.doc_id,
        chunk_index=chunk_index,
        heading_path=heading_path,
        chunk_tags=doc_meta.tags,  # Inherit document tags
    )

    # Build the LanceDB record with all metadata fields
    record = {
        "id": chunk_id,
        "text": chunk_text,
        "source": doc_meta.source_path,
        "source_type": doc_meta.source_type,
        "heading": heading,
        "chunk_index": chunk_index,
        "embedded_at": datetime.now().timestamp(),
        # New metadata fields
        "doc_id": doc_meta.doc_id,
        "title": doc_meta.title,
        "domain": doc_meta.domain,
        "content_format": doc_meta.content_format,
        "topic": doc_meta.topic,
        "status": doc_meta.status,
        "language": doc_meta.language,
        "tags": ",".join(doc_meta.tags),
        "keywords": ",".join(doc_meta.keywords),
        "content_hash": doc_meta.content_hash,
        "chunk_strategy": doc_meta.chunk_strategy,
    }

    return chunk_meta.__dict__, record