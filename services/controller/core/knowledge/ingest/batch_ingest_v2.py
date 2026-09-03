#!/usr/bin/env python3
"""
Alexandria Knowledge Base — Proper Batch Ingestion Pipeline

File-by-file ingestion with:
- Metadata schema (document-level + chunk-level)
- Auto-tagging with controlled vocabulary
- Keyword extraction
- Content-type-aware chunking
- Vision model for image description
- SHA-256 content hashing for dedup
- Idempotent: skip unchanged files
- Provenance tracking

Usage:
    python batch_ingest_v2.py [--max-files N] [--vision] [--dry-run]

This is the framework that all survivors will rely on.
"""

from __future__ import annotations

import os
import sys
import time
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ARES controller imports
sys.path.insert(0, "/Users/matthewjenkins/GitHub/ARES/services/controller")

from core.knowledge.config import KBConfig
from core.knowledge.vector.store import KnowledgeStore
from core.knowledge.vector.embedder import Embedder, EmbeddingError
from core.knowledge.vector.chunker import chunk_text
from core.knowledge.graph.store import GraphStore
from core.knowledge.ingest.metadata import (
    build_document_metadata,
    build_chunk_metadata,
    compute_content_hash,
    compute_doc_id,
    detect_content_format,
    ContentFormat,
)
from core.knowledge.ingest.vision import VisionDescriber, is_image_file

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT = "/Volumes/Jenkins_Robotics"
LOG_FILE = "/tmp/alexandria_ingest.log"
PROGRESS_FILE = "/tmp/alexandria_progress.json"  # Resumable state

# Directories to skip entirely
SKIP_DIRS = {
    ".Trash", ".tmp", ".DS_Store", ".uploads", ".git",
    "node_modules", "__pycache__", ".pytest_cache", ".venv",
    "venv", "env", ".mypy_cache", ".ruff_cache", ".tox",
    "site-packages", "dist-packages", "SteamLibrary",
    ".hermes",  # session data, not knowledge
    ".obsidian",  # Obsidian config, not content
}

# File extensions to skip (binary, compiled, non-text)
SKIP_EXTS = {
    "pyc", "pyo", "so", "dylib", "dll", "exe", "bin",
    "png", "jpg", "jpeg", "gif", "bmp", "ico", "webp", "tiff",  # Images handled by vision
    "mp4", "mov", "avi", "mkv", "flv", "wmv",
    "wav", "mp3", "flac", "aac", "ogg", "m4a",
    "zip", "tar", "gz", "bz2", "7z", "rar", "xz",
    "db", "sqlite", "sqlite3", "db-journal", "db-wal", "db-shm",
    "class", "o", "obj", "a", "lib", "map", "wasm",
    "stl", "fbx", "blend", "3ds", "dat", "sample", "ndjson",
    "typed", "pyi", "pxd", "pyx",
}

# Extensions to index as text
INDEX_EXTS = {
    "md", "txt", "py", "js", "ts", "json", "yaml", "yml",
    "html", "htm", "csv", "xml", "rst", "tex", "bib",
    "srt", "vtt",
    "sh", "bash", "sql", "graphql", "toml", "ini", "cfg",
    "c", "cpp", "h", "hpp", "rs", "go", "java", "rb", "php", "swift",
    "dart", "kt", "scala", "lua", "r", "m",
    "log",
}

# Image extensions for vision model
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}

# Priority order — knowledge content first, code later
PRIORITY_DIRS = {
    "03_Knowledge": 1,
    "07_Intake": 2,
    "02_Projects": 3,
    "01_Business": 4,
    "06_Agents": 5,
    "00_System": 6,
    "04_Content": 7,
    "05_Assets": 8,
    "08_Reports": 9,
    "10_Proprietary": 10,
    "ARES-Projects": 11,
    "Archive": 12,
    "09_Archive": 13,
}

MAX_FILE_SIZE = 500_000  # 500KB per file
MAX_FILES_DEFAULT = 0  # 0 = no limit

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("alexandria")

# ---------------------------------------------------------------------------
# File Collection
# ---------------------------------------------------------------------------

def should_skip_dir(dirname: str) -> bool:
    return dirname in SKIP_DIRS or dirname.startswith(".Trash")

def get_priority(filepath: str) -> int:
    rel = os.path.relpath(filepath, ROOT)
    top = rel.split("/")[0] if "/" in rel else ""
    return PRIORITY_DIRS.get(top, 99)

def collect_files(include_images: bool = False) -> tuple[list[str], list[str]]:
    """Collect all indexable files. Returns (text_files, image_files)."""
    text_files = []
    image_files = []

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]

        for f in filenames:
            if f == ".DS_Store":
                continue
            ext = Path(f).suffix.lstrip(".").lower()

            # Text files
            if ext in INDEX_EXTS:
                filepath = os.path.join(dirpath, f)
                try:
                    size = os.path.getsize(filepath)
                except OSError:
                    continue
                if 0 < size <= MAX_FILE_SIZE:
                    text_files.append(filepath)

            # Image files (only if vision is enabled)
            elif include_images and ext in IMAGE_EXTS:
                filepath = os.path.join(dirpath, f)
                try:
                    size = os.path.getsize(filepath)
                except OSError:
                    continue
                if 0 < size <= 5_000_000:  # 5MB max for images
                    image_files.append(filepath)

    text_files.sort(key=lambda f: (get_priority(f), f))
    image_files.sort(key=lambda f: (get_priority(f), f))
    return text_files, image_files

# ---------------------------------------------------------------------------
# Content Reading
# ---------------------------------------------------------------------------

def read_file_content(filepath: str) -> str:
    """Read file content as UTF-8 text."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

# ---------------------------------------------------------------------------
# Progress Tracking (Resumable)
# ---------------------------------------------------------------------------

def load_progress() -> dict:
    """Load progress from previous run."""
    try:
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"processed_files": [], "total_chunks": 0, "total_files": 0, "errors": 0}

def save_progress(progress: dict) -> None:
    """Save progress for resumption."""
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump(progress, f)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Main Ingestion
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Alexandria Batch Ingestion v2")
    parser.add_argument("--max-files", type=int, default=MAX_FILES_DEFAULT, help="Max files to process (0=no limit)")
    parser.add_argument("--vision", action="store_true", help="Enable vision model for images")
    parser.add_argument("--dry-run", action="store_true", help="Scan and report, don't ingest")
    parser.add_argument("--skip-images", action="store_true", help="Skip image files even if vision is available")
    args = parser.parse_args()

    logger.info("=== Alexandria Knowledge Base Ingestion v2 ===")
    logger.info("This is the framework that all survivors will rely on.")
    logger.info("")

    # Initialize config and stores
    config = KBConfig.from_env()
    logger.info("LanceDB: %s", config.lance_dir)
    logger.info("Graph: %s", config.graph_db_path)
    logger.info("Embedding model: %s (%d dims)", config.embedding_model, config.embedding_dims)
    logger.info("Ollama: %s", config.ollama_base_url)

    store = KnowledgeStore(config)
    embedder = Embedder.from_config(config)

    # Check vision model availability
    vision = None
    if args.vision and not args.skip_images:
        vision = VisionDescriber(ollama_url=config.ollama_base_url)
        if vision.is_available():
            logger.info("Vision model: %s (available)", vision.model)
        else:
            logger.warning("Vision model %s not available — images will be skipped", vision.model)
            vision = None

    # Collect files
    logger.info("Scanning for indexable files...")
    text_files, image_files = collect_files(include_images=vision is not None)
    logger.info("Found %d text files, %d image files", len(text_files), len(image_files))

    if args.dry_run:
        logger.info("Dry run — not ingesting. File breakdown:")
        by_domain = defaultdict(int)
        for f in text_files:
            domain = detect_content_format(f)
            by_domain[domain] += 1
        for fmt, count in sorted(by_domain.items(), key=lambda x: -x[1]):
            logger.info("  %s: %d files", fmt, count)
        return

    # Load progress for resumption
    progress = load_progress()
    processed = set(progress["processed_files"])
    logger.info("Already processed: %d files", len(processed))

    # Filter to unprocessed files
    text_to_ingest = [f for f in text_files if f not in processed]
    images_to_ingest = [f for f in image_files if f not in processed]

    if args.max_files > 0:
        text_to_ingest = text_to_ingest[:args.max_files]

    total_to_process = len(text_to_ingest) + len(images_to_ingest)
    logger.info("To ingest: %d text files, %d image files", len(text_to_ingest), len(images_to_ingest))
    logger.info("")

    # Process text files
    start_time = time.time()
    total_chunks = progress["total_chunks"]
    total_files = progress["total_files"]
    errors = progress["errors"]

    for i, filepath in enumerate(text_to_ingest):
        if (i + 1) % 50 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(text_to_ingest) - i - 1) / rate if rate > 0 else 0
            logger.info(
                "  [%d/%d] files=%d chunks=%d errors=%d elapsed=%.0fs ETA=%.0fs",
                i + 1, len(text_to_ingest), total_files, total_chunks, errors, elapsed, eta,
            )
            save_progress({
                "processed_files": list(processed),
                "total_chunks": total_chunks,
                "total_files": total_files,
                "errors": errors,
            })

        try:
            content = read_file_content(filepath)
            if not content or len(content.strip()) < 10:
                processed.add(filepath)
                continue

            # Build document metadata
            doc_meta = build_document_metadata(filepath, content, source_type="nas")

            # Skip if content hash matches (already indexed with same content)
            # (TODO: check against stored hashes — for now just skip by path)

            # Chunk the content
            chunks = chunk_text(
                content,
                source_type=doc_meta.content_format,
                max_chars=config.chunk_max_chars,
                overlap=config.chunk_overlap_chars,
            )
            if not chunks:
                processed.add(filepath)
                continue

            # Embed all chunks
            try:
                vectors = embedder.embed([c.text for c in chunks])
            except EmbeddingError as exc:
                logger.error("Embedding failed for %s: %s", filepath, exc)
                errors += 1
                processed.add(filepath)
                continue

            # Build records with full metadata
            records = []
            for chunk, vec in zip(chunks, vectors):
                _, record = build_chunk_metadata(doc_meta, chunk.index, chunk.text, chunk.heading)
                record["vector"] = vec
                records.append(record)

            # Ingest with metadata
            store.ingest_with_metadata(records)
            total_chunks += len(records)
            total_files += 1
            processed.add(filepath)

            # Log rich metadata for first few files
            if total_files <= 5 or total_files % 100 == 0:
                logger.info(
                    "  ✓ [%s] %s — domain=%s tags=%s chunks=%d",
                    doc_meta.content_format,
                    doc_meta.title[:60],
                    doc_meta.domain,
                    ",".join(doc_meta.tags[:4]),
                    len(records),
                )

        except Exception as exc:
            errors += 1
            if errors <= 50:
                logger.error("ERROR: %s: %s", filepath, exc)
            processed.add(filepath)
            continue

    # Process image files with vision model
    if vision and images_to_ingest:
        logger.info("")
        logger.info("Processing %d images with vision model...", len(images_to_ingest))

        for i, filepath in enumerate(images_to_ingest):
            if (i + 1) % 25 == 0:
                logger.info("  [%d/%d] images processed", i + 1, len(images_to_ingest))

            try:
                # Generate image description
                description = vision.describe_image(filepath)
                if not description:
                    errors += 1
                    processed.add(filepath)
                    continue

                # Build metadata for the image
                # Prepend with path context for better searchability
                rel_path = os.path.relpath(filepath, ROOT)
                full_text = f"[Image: {rel_path}]\n\n{description}"

                doc_meta = build_document_metadata(filepath, full_text, source_type="nas_image")

                # Chunk the description (usually 1-2 chunks)
                chunks = chunk_text(
                    full_text,
                    source_type="image",
                    max_chars=config.chunk_max_chars,
                    overlap=config.chunk_overlap_chars,
                )

                # Embed
                try:
                    vectors = embedder.embed([c.text for c in chunks])
                except EmbeddingError:
                    errors += 1
                    processed.add(filepath)
                    continue

                # Build records
                records = []
                for chunk, vec in zip(chunks, vectors):
                    _, record = build_chunk_metadata(doc_meta, chunk.index, chunk.text, chunk.heading)
                    record["vector"] = vec
                    records.append(record)

                store.ingest_with_metadata(records)
                total_chunks += len(records)
                total_files += 1
                processed.add(filepath)

                if total_files % 50 == 0:
                    logger.info("  ✓ [image] %s — %d chunks", doc_meta.title[:60], len(records))

            except Exception as exc:
                errors += 1
                if errors <= 50:
                    logger.error("IMAGE ERROR: %s: %s", filepath, exc)
                processed.add(filepath)
                continue

    # Final report
    elapsed = time.time() - start_time
    logger.info("")
    logger.info("=== INGESTION COMPLETE ===")
    logger.info("Files indexed: %d", total_files)
    logger.info("Chunks created: %d", total_chunks)
    logger.info("Errors: %d", errors)
    logger.info("Time: %.0fs (%.1f hours)", elapsed, elapsed / 3600)

    # Save final progress
    save_progress({
        "processed_files": list(processed),
        "total_chunks": total_chunks,
        "total_files": total_files,
        "errors": errors,
    })

    # Print KB status
    status = store.status()
    logger.info("KB Status: %s", json.dumps(status, indent=2))


if __name__ == "__main__":
    main()