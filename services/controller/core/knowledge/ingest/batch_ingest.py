#!/usr/bin/env python3
"""
Batch ingest all text content from the Jenkins_Robotics NAS share into the Alexandria KB.
Runs directly on the host, bypassing the MCP gateway for speed.
Reads files, chunks them, generates embeddings via Ollama, and bulk-inserts into LanceDB.
Also extracts entities for the GraphRAG store.
"""
import os
import sys
import time
import json
from pathlib import Path
from collections import defaultdict

# ARES controller imports
sys.path.insert(0, "/Users/matthewjenkins/GitHub/ARES/services/controller")

from core.knowledge.config import KBConfig
from core.knowledge.vector.store import KnowledgeStore
from core.knowledge.vector.embedder import Embedder
from core.knowledge.vector.chunker import chunk_text
from core.knowledge.graph.store import GraphStore
from core.knowledge.graph.extractor import extract

ROOT = "/Volumes/Jenkins_Robotics"
SKIP_DIRS = {
    ".Trash", ".tmp", ".DS_Store", ".uploads", ".git",
    "node_modules", "__pycache__", ".pytest_cache", ".venv",
    "venv", "env", ".mypy_cache", ".ruff_cache", ".tox",
    "site-packages", "dist-packages", "SteamLibrary",
    ".hermes",  # session data, not knowledge
}
SKIP_EXTS = {
    "pyc", "pyo", "so", "dylib", "dll", "exe", "bin",
    "png", "jpg", "jpeg", "gif", "bmp", "ico", "webp", "tiff",
    "mp4", "mov", "avi", "mkv", "flv", "wmv",
    "wav", "mp3", "flac", "aac", "ogg", "m4a",
    "zip", "tar", "gz", "bz2", "7z", "rar", "xz",
    "db", "sqlite", "sqlite3", "db-journal", "db-wal", "db-shm",
    "class", "o", "obj", "a", "lib", "map", "wasm",
    "stl", "fbx", "blend", "3ds", "dat", "sample", "ndjson",
    "ino", "qml",  # code we don't need to index
    "typed", "pyi", "pxd", "pyx",  # type stubs
    "xsd", "config", "procps",
}
INDEX_EXTS = {
    "md", "txt", "py", "js", "ts", "json", "yaml", "yml",
    "html", "htm", "csv", "xml", "rst", "tex", "bib",
    "srt", "vtt",
    "sh", "bash", "sql", "graphql", "toml", "ini", "cfg",
    "c", "cpp", "h", "hpp", "rs", "go", "java", "rb", "php", "swift",
    "dart", "kt", "scala", "lua", "r", "m",
    "log",
}
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

def should_skip_dir(dirname):
    return dirname in SKIP_DIRS or dirname.startswith(".Trash")

def get_priority(filepath):
    rel = os.path.relpath(filepath, ROOT)
    top = rel.split("/")[0] if "/" in rel else ""
    return PRIORITY_DIRS.get(top, 99)

def collect_files():
    """Collect all indexable files, sorted by priority."""
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Filter dirs in-place
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]

        for f in filenames:
            if f == ".DS_Store":
                continue
            ext = Path(f).suffix.lstrip(".").lower()
            if ext in SKIP_EXTS or ext not in INDEX_EXTS:
                continue
            filepath = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(filepath)
            except OSError:
                continue
            if size > MAX_FILE_SIZE or size == 0:
                continue
            files.append(filepath)

    # Sort by priority (knowledge content first, code later)
    files.sort(key=lambda f: (get_priority(f), f))
    return files

def read_file_content(filepath):
    """Read file content as text."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

def main():
    print("=== Alexandria Batch Ingestion ===", flush=True)
    config = KBConfig.from_env()
    print(f"LanceDB: {config.lance_dir}", flush=True)
    print(f"Graph: {config.graph_db_path}", flush=True)
    print(f"Embedding model: {config.embedding_model}", flush=True)
    print(f"Ollama: {config.ollama_base_url}", flush=True)

    # Initialize stores
    store = KnowledgeStore(config)
    graph_store = GraphStore(config)

    # Collect files
    print("Scanning for indexable files...", flush=True)
    files = collect_files()
    print(f"Found {len(files)} indexable files", flush=True)

    # Track what's already indexed
    existing_sources = store.get_existing_sources()
    print(f"Already indexed: {len(existing_sources)} sources", flush=True)

    # Filter out already-indexed files
    files_to_ingest = [f for f in files if f not in existing_sources]
    print(f"Files to ingest: {len(files_to_ingest)} (skipping {len(files) - len(files_to_ingest)} already indexed)", flush=True)
    files = files_to_ingest

    # Batch ingest
    total_chunks = 0
    total_files = 0
    total_entities = 0
    total_relationships = 0
    errors = 0
    start_time = time.time()

    for i, filepath in enumerate(files):
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(files) - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1}/{len(files)}] {total_files} files indexed, {total_chunks} chunks, "
                  f"{total_entities} entities, {elapsed:.0f}s elapsed, ETA {eta:.0f}s", flush=True)

        try:
            content = read_file_content(filepath)
            if not content or len(content.strip()) < 10:
                continue

            # Determine source type
            rel = os.path.relpath(filepath, ROOT)
            top_dir = rel.split("/")[0] if "/" in rel else "root"
            source_type = {
                "03_Knowledge": "notes",
                "07_Intake": "intake",
                "02_Projects": "projects",
                "01_Business": "business",
                "06_Agents": "agents",
                "00_System": "system",
                "04_Content": "content",
                "05_Assets": "assets",
                "08_Reports": "reports",
                "10_Proprietary": "proprietary",
                "ARES-Projects": "projects",
                "Archive": "archive",
                "09_Archive": "archive",
            }.get(top_dir, "text")

            # Ingest into vector store (chunks + embeds internally)
            chunk_count = store.ingest(
                text=content,
                source=filepath,
                source_type=source_type,
            )
            total_chunks += chunk_count

            # Skip entity extraction during batch ingest — it's too slow
            # and competes with embeddings for Ollama. Run graph build separately after.
            total_files += 1

        except Exception as e:
            errors += 1
            if errors <= 20:
                print(f"  ERROR: {filepath}: {e}", flush=True)
            continue

    elapsed = time.time() - start_time
    print(f"\n=== INGESTION COMPLETE ===", flush=True)
    print(f"Files indexed: {total_files}", flush=True)
    print(f"Chunks created: {total_chunks}", flush=True)
    print(f"Entities extracted: {total_entities}", flush=True)
    print(f"Relationships: {total_relationships}", flush=True)
    print(f"Errors: {errors}", flush=True)
    print(f"Time: {elapsed:.0f}s", flush=True)

    # Print final KB status
    status = store.status()
    print(f"\nKB Status: {json.dumps(status, indent=2)}", flush=True)
    graph_status = graph_store.status()
    print(f"Graph Status: {json.dumps(graph_status, indent=2)}", flush=True)

if __name__ == "__main__":
    main()