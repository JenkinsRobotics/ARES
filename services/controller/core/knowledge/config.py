"""Configuration for the ARES Knowledge Base.

Single source of truth for paths, embedding model, and store settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass


# --- Paths ---

def _alexandria_root() -> Path:
    """Root data directory on the NAS."""
    env = os.environ.get("ARES_KB_ROOT", "")
    if env:
        return Path(env).expanduser()
    return Path("/Volumes/Jenkins_Robotics/Alexandria")


@dataclass(frozen=True)
class KBConfig:
    root: Path
    lance_dir: Path
    graph_dir: Path
    honcho_dir: Path
    sources_dir: Path

    # Embedding
    embedding_model: str
    embedding_dims: int
    ollama_base_url: str

    # LanceDB
    table_name: str
    chunk_max_chars: int
    chunk_overlap_chars: int

    # GraphRAG
    graph_db_path: Path
    entity_extraction_model: str

    # Honcho
    honcho_api_url: str

    @classmethod
    def from_env(cls) -> "KBConfig":
        nas_root = _alexandria_root()
        # LanceDB index lives on local disk — Lance format needs POSIX atomic renames
        # which SMB doesn't support. Sources stay on the NAS.
        local_root = Path(os.environ.get(
            "ARES_KB_LOCAL_ROOT",
            str(Path.home() / ".ares" / "alexandria"),
        ))
        return cls(
            root=nas_root,
            lance_dir=local_root / "lance",
            graph_dir=local_root / "graph",
            honcho_dir=local_root / "honcho",
            sources_dir=nas_root / "sources",
            embedding_model=os.environ.get("ARES_KB_EMBEDDING_MODEL", "mxbai-embed-large"),
            embedding_dims=int(os.environ.get("ARES_KB_EMBEDDING_DIMS", "1024")),
            ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            table_name=os.environ.get("ARES_KB_TABLE", "documents"),
            chunk_max_chars=int(os.environ.get("ARES_KB_CHUNK_MAX", "800")),
            chunk_overlap_chars=int(os.environ.get("ARES_KB_CHUNK_OVERLAP", "150")),
            graph_db_path=local_root / "graph" / "graph.db",
            entity_extraction_model=os.environ.get("ARES_KB_GRAPH_MODEL", "qwen2.5:3b"),
            honcho_api_url=os.environ.get("HONCHO_API_URL", "http://100.78.245.49:8088"),
        )