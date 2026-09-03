"""Knowledge graph storage using SQLite + NetworkX.

Stores entities, relationships, and community summaries.
Supports multi-hop traversal and community-based queries.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..config import KBConfig
from .extractor import Entity, Relationship, ExtractionResult

logger = logging.getLogger(__name__)


def _init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            entity_type TEXT NOT NULL DEFAULT 'other',
            description TEXT DEFAULT '',
            source TEXT DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_entity TEXT NOT NULL,
            target_entity TEXT NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'relates_to',
            description TEXT DEFAULT '',
            source TEXT DEFAULT '',
            confidence REAL DEFAULT 1.0,
            created_at REAL NOT NULL,
            FOREIGN KEY (source_entity) REFERENCES entities(name),
            FOREIGN KEY (target_entity) REFERENCES entities(name)
        );

        CREATE TABLE IF NOT EXISTS communities (
            id INTEGER PRIMARY KEY,
            level INTEGER NOT NULL DEFAULT 0,
            entity_names TEXT NOT NULL,
            summary TEXT DEFAULT '',
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_entity);
        CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_entity);
        CREATE INDEX IF NOT EXISTS idx_ent_type ON entities(entity_type);
    """)
    conn.commit()
    return conn


class GraphStore:
    """SQLite-backed knowledge graph with NetworkX for traversal."""

    def __init__(self, config: KBConfig) -> None:
        self.config = config
        self.db_path = Path(config.graph_db_path)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _init_db(self.db_path)
        return self._conn

    def add_extraction(self, result: ExtractionResult) -> int:
        """Add entities and relationships from an extraction result."""
        now = time.time()
        added = 0
        for entity in result.entities:
            if not entity.name:
                continue
            try:
                self.conn.execute(
                    """INSERT INTO entities (name, entity_type, description, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(name) DO UPDATE SET
                         description=excluded.description,
                         source=excluded.source,
                         updated_at=excluded.updated_at""",
                    (entity.name, entity.entity_type, entity.description, entity.source, now, now),
                )
                added += 1
            except sqlite3.Error as exc:
                logger.debug("Entity insert failed: %s", exc)

        for rel in result.relationships:
            if not rel.source_entity or not rel.target_entity:
                continue
            # Ensure both entities exist
            for name, etype in [(rel.source_entity, "other"), (rel.target_entity, "other")]:
                try:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO entities (name, entity_type, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (name, etype, now, now),
                    )
                except sqlite3.Error:
                    pass
            try:
                self.conn.execute(
                    """INSERT INTO relationships (source_entity, target_entity, relation_type, description, source, confidence, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (rel.source_entity, rel.target_entity, rel.relation_type, rel.description, rel.source, rel.confidence, now),
                )
                added += 1
            except sqlite3.Error as exc:
                logger.debug("Relationship insert failed: %s", exc)

        self.conn.commit()
        return added

    def query(self, query: str, depth: int = 2, mode: str = "local") -> dict[str, Any]:
        """Query the knowledge graph.

        Args:
            query: Natural language query
            depth: Traversal depth (1-4)
            mode: local (entity-centric), global (community), drift (hybrid)
        """
        try:
            import networkx as nx
        except ImportError:
            return self._query_sqlite(query, depth, mode)

        graph = self._build_networkx()
        if graph.number_of_nodes() == 0:
            return {"answer": "", "path": [], "evidence": [], "note": "Graph is empty"}

        # Find matching entities by name similarity
        query_lower = query.lower()
        matches = [n for n in graph.nodes if any(w in n.lower() for w in query_lower.split() if len(w) > 2)]

        if not matches:
            return {"answer": "", "path": [], "evidence": [], "note": "No matching entities found"}

        # Traverse from matches up to depth
        visited = set()
        paths = []
        for start in matches[:5]:  # Limit starting points
            for target in graph.nodes:
                if target == start or target in visited:
                    continue
                try:
                    path = nx.shortest_path(graph, source=start, target=target)
                    if len(path) <= depth + 1:
                        paths.append(path)
                        visited.update(path)
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue

        # Build evidence from paths
        evidence = []
        for path in paths[:10]:
            path_evidence = {"path": path, "edges": []}
            for i in range(len(path) - 1):
                edge_data = graph.get_edge_data(path[i], path[i+1])
                if edge_data:
                    path_evidence["edges"].append({
                        "from": path[i],
                        "to": path[i+1],
                        "relation": edge_data.get("relation", "relates_to"),
                        "description": edge_data.get("description", ""),
                    })
            evidence.append(path_evidence)

        return {
            "answer": f"Found {len(paths)} paths from {len(matches)} matching entities",
            "matched_entities": matches[:10],
            "paths": [p for p in paths[:10]],
            "evidence": evidence[:10],
            "total_entities": graph.number_of_nodes(),
            "total_relationships": graph.number_of_edges(),
        }

    def _query_sqlite(self, query: str, depth: int, mode: str) -> dict[str, Any]:
        """Fallback query without NetworkX."""
        query_lower = query.lower()
        rows = self.conn.execute(
            "SELECT name, entity_type, description FROM entities WHERE name LIKE ? LIMIT 20",
            (f"%{query}%",),
        ).fetchall()
        if not rows:
            return {"answer": "", "path": [], "evidence": [], "note": "No matching entities"}
        return {
            "answer": f"Found {len(rows)} matching entities",
            "matched_entities": [{"name": r[0], "type": r[1], "description": r[2]} for r in rows],
            "evidence": [],
        }

    def _build_networkx(self):
        import networkx as nx
        graph = nx.DiGraph()
        for row in self.conn.execute("SELECT name, entity_type, description FROM entities").fetchall():
            graph.add_node(row[0], entity_type=row[1], description=row[2])
        for row in self.conn.execute("SELECT source_entity, target_entity, relation_type, description FROM relationships").fetchall():
            graph.add_edge(row[0], row[1], relation=row[2], description=row[3])
        return graph

    def status(self) -> dict[str, Any]:
        try:
            entity_count = self.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            rel_count = self.conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
            community_count = self.conn.execute("SELECT COUNT(*) FROM communities").fetchone()[0]
            return {
                "available": True,
                "entity_count": entity_count,
                "relationship_count": rel_count,
                "community_count": community_count,
                "graph_db_path": str(self.db_path),
            }
        except sqlite3.Error as exc:
            return {"available": False, "error": str(exc), "entity_count": 0}

    def remove_source(self, source: str) -> int:
        try:
            self.conn.execute("DELETE FROM relationships WHERE source = ?", (source,))
            self.conn.execute("DELETE FROM entities WHERE source = ?", (source,))
            self.conn.commit()
            return 1
        except sqlite3.Error:
            return 0

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None