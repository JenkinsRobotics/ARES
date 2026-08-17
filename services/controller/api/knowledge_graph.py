"""Knowledge graph and vault metadata extractor for ARES Memory Tab.

Parses markdown knowledge vaults (e.g. Obsidian vaults, NAS folders, local docs)
extracting wikilinks [[...]], markdown links, tags, and cluster hierarchies for
force-directed graph visualization and document inspection.

Features high-performance SQLite caching so subsequent graph loads across network
shares (SMB NAS) return in milliseconds.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

IGNORE_DIRS = {
    "steamlibrary", "steam", "node_modules", ".git", ".venv", "venv",
    "__pycache__", ".pytest_cache", ".agent", "archive",
    ".cache", "dist", "build", ".next", ".nuxt", "temp", "tmp",
}


def _cache_db_path() -> Path:
    p = Path.home() / ".ares" / "knowledge_graph_cache.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _get_cache_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_cache_db_path()), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_cache (
            full_path   TEXT PRIMARY KEY,
            mtime       REAL,
            node_id     TEXT,
            title       TEXT,
            rel_path    TEXT,
            cluster     TEXT,
            tags        TEXT,
            links       TEXT,
            size        INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_mtime ON doc_cache(mtime)")
    return conn


def _get_rag_sources() -> list[dict[str, Any]]:
    """Load configured RAG sources from ~/.ares/rag_sources.yaml."""
    cfg_file = Path.home() / ".ares" / "rag_sources.yaml"
    if not cfg_file.exists():
        return [{"path": "/Volumes/Jenkins_Robotics/03_Knowledge", "enabled": True}]
    try:
        data = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
        sources = data.get("sources", [])
        if not sources and Path("/Volumes/Jenkins_Robotics/03_Knowledge").exists():
            return [{"path": "/Volumes/Jenkins_Robotics/03_Knowledge", "enabled": True}]
        return sources
    except Exception as exc:
        logger.debug("Failed reading rag_sources.yaml: %s", exc)
        return []


def _resolve_knowledge_folders(sources: list[str] | None = None) -> list[Path]:
    target_folders: list[Path] = []
    if sources:
        for s in sources:
            p = Path(s).expanduser()
            if p.exists() and p.is_dir():
                target_folders.append(p)
    else:
        configured = _get_rag_sources()
        for src in configured:
            raw_p = (src.get("path") or "").strip() if isinstance(src, dict) else str(src).strip()
            if not raw_p:
                continue
            p = Path(raw_p).expanduser()
            if p.exists():
                if p.is_dir():
                    # If this is /Volumes/Jenkins_Robotics and 03_Knowledge exists, scope to 03_Knowledge
                    if (p / "03_Knowledge").exists():
                        target_folders.append(p / "03_Knowledge")
                    else:
                        target_folders.append(p)
                elif p.is_file() and p.suffix == ".md":
                    target_folders.append(p.parent)

    if not target_folders:
        default_nas = Path("/Volumes/Jenkins_Robotics/03_Knowledge")
        if default_nas.exists():
            target_folders.append(default_nas)
        default_local = Path.home() / ".ares" / "knowledge"
        if default_local.exists():
            target_folders.append(default_local)

    return target_folders


def _parse_file(file_path: Path, base_folder: Path, mtime: float) -> dict[str, Any]:
    try:
        rel_path = str(file_path.relative_to(base_folder))
    except ValueError:
        rel_path = file_path.name

    parts = rel_path.split(os.sep)
    cluster = parts[0] if len(parts) > 1 else "General"
    if cluster.endswith(".md"):
        cluster = "General"

    title = file_path.stem.replace("_", " ").replace("-", " ").title()

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        content = ""

    for line in content.splitlines()[:5]:
        line = line.strip()
        if line.startswith("# "):
            h1 = line[2:].strip()
            if h1:
                title = h1
                break

    tags = list(set(re.findall(r"(?:^|\s)#([a-zA-Z0-9_\-]+)", content)))
    raw_wikilinks = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", content)
    wikilinks = [Path(wl.strip().replace("%20", " ")).stem.lower() for wl in raw_wikilinks if wl.strip()]

    raw_mdlinks = re.findall(r"\[([^\]]+)\]\(([^)]+\.md)\)", content)
    for _, target in raw_mdlinks:
        clean = Path(target.strip().replace("%20", " ")).stem.lower()
        if clean and clean not in wikilinks:
            wikilinks.append(clean)

    node_id = file_path.stem.lower()
    return {
        "full_path": str(file_path),
        "mtime": mtime,
        "node_id": node_id,
        "title": title,
        "rel_path": rel_path,
        "cluster": cluster,
        "tags": tags,
        "links": wikilinks,
        "size": len(content),
    }


def build_knowledge_graph(
    sources: list[str] | None = None,
    max_nodes: int = 500,
    query: str | None = None,
    tag: str | None = None,
    cluster: str | None = None,
) -> dict[str, Any]:
    """Scan knowledge folders and return physics graph payload with SQLite caching."""
    target_folders = _resolve_knowledge_folders(sources)
    if not target_folders:
        return {
            "ok": True,
            "nodes": [],
            "links": [],
            "clusters": [],
            "tags": [],
            "stats": {"total_documents": 0, "visible_nodes": 0, "visible_links": 0, "total_tags": 0, "sources": []},
            "message": "No knowledge folders configured.",
        }

    conn = _get_cache_conn()
    cached_rows = {
        row[0]: {
            "mtime": row[1],
            "node_id": row[2],
            "title": row[3],
            "rel_path": row[4],
            "cluster": row[5],
            "tags": json.loads(row[6]),
            "links": json.loads(row[7]),
            "size": row[8],
        }
        for row in conn.execute("SELECT full_path, mtime, node_id, title, rel_path, cluster, tags, links, size FROM doc_cache").fetchall()
    }

    all_docs: list[dict[str, Any]] = []
    to_upsert: list[tuple] = []

    for folder in target_folders:
        for root, dirs, filenames in os.walk(folder):
            dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS and not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(".md") and not fn.startswith("."):
                    full_p = os.path.join(root, fn)
                    try:
                        mtime = os.path.getmtime(full_p)
                    except OSError:
                        continue

                    cached = cached_rows.get(full_p)
                    if cached and cached["mtime"] == mtime:
                        doc = dict(cached)
                        doc["full_path"] = full_p
                        all_docs.append(doc)
                    else:
                        doc = _parse_file(Path(full_p), folder, mtime)
                        all_docs.append(doc)
                        to_upsert.append((
                            full_p, mtime, doc["node_id"], doc["title"],
                            doc["rel_path"], doc["cluster"],
                            json.dumps(doc["tags"]), json.dumps(doc["links"]), doc["size"]
                        ))

    if to_upsert:
        with conn:
            conn.executemany("""
                INSERT OR REPLACE INTO doc_cache(full_path, mtime, node_id, title, rel_path, cluster, tags, links, size)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, to_upsert)

    conn.close()

    # Filter
    filtered = all_docs
    if query and query.strip():
        q = query.strip().lower()
        filtered = [d for d in filtered if q in d["title"].lower() or q in d["node_id"] or q in d["rel_path"].lower()]

    if tag and tag.strip():
        t_clean = tag.strip().lstrip("#").lower()
        filtered = [d for d in filtered if any(t_clean == tg.lower() for tg in d["tags"])]

    if cluster and cluster.strip():
        c_clean = cluster.strip().lower()
        filtered = [d for d in filtered if d["cluster"].lower() == c_clean]

    total_scanned = len(filtered)
    # Sort by connectivity and recency
    filtered.sort(key=lambda d: (len(d["links"]), d["mtime"]), reverse=True)
    selected = filtered[:max_nodes]
    selected_ids = {d["node_id"] for d in selected}

    links = []
    link_pairs = set()
    inbound_counts: dict[str, int] = {nid: 0 for nid in selected_ids}

    for node in selected:
        src = node["node_id"]
        for target in node["links"]:
            if target in selected_ids and target != src:
                pair = tuple(sorted([src, target]))
                if pair not in link_pairs:
                    link_pairs.add(pair)
                    links.append({"source": src, "target": target})
                    inbound_counts[target] = inbound_counts.get(target, 0) + 1

    nodes_payload = []
    clusters_set = set()
    tags_set = set()

    for node in selected:
        nid = node["node_id"]
        degree = len(node["links"]) + inbound_counts.get(nid, 0)
        clusters_set.add(node["cluster"])
        for tg in node["tags"]:
            tags_set.add(tg)

        nodes_payload.append({
            "id": nid,
            "title": node["title"],
            "rel_path": node["rel_path"],
            "full_path": node["full_path"],
            "cluster": node["cluster"],
            "tags": node["tags"][:5],
            "degree": degree,
            "size": min(22, max(6, 6 + degree * 2)),
            "mtime": node["mtime"],
        })

    return {
        "ok": True,
        "nodes": nodes_payload,
        "links": links,
        "clusters": sorted(clusters_set),
        "tags": sorted(tags_set)[:30],
        "stats": {
            "total_documents": total_scanned,
            "visible_nodes": len(nodes_payload),
            "visible_links": len(links),
            "total_tags": len(tags_set),
            "sources": [str(p) for p in target_folders],
        },
    }


def read_knowledge_document(file_path: str) -> dict[str, Any]:
    """Read document content and metadata for graph inspection drawer."""
    p = Path(file_path).expanduser()
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": f"File '{file_path}' does not exist."}

    try:
        content = p.read_text(encoding="utf-8", errors="ignore")
        return {
            "ok": True,
            "title": p.stem.replace("_", " ").replace("-", " ").title(),
            "full_path": str(p),
            "file_name": p.name,
            "size_bytes": len(content),
            "mtime": p.stat().st_mtime,
            "content": content,
        }
    except Exception as exc:
        return {"ok": False, "error": f"Failed reading file: {exc}"}
