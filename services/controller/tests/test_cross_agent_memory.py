"""
Tests for Multi-Agent Cross-Agent Memory Synchronization and Distillation.
"""

import json
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from core.memory.cross_agent_sync import (
    distill_facts_from_corpus,
    filter_high_signal_items,
    generate_person_md,
    get_cross_agent_profile,
    get_cross_agent_status,
    sync_cross_agent_memory,
)
from core.memory.journal.import_hermes import import_hermes


@pytest.fixture
def temp_ares_env(monkeypatch, tmp_path):
    ares_home = tmp_path / ".ares"
    ares_home.mkdir()
    monkeypatch.setenv("ARES_HOME", str(ares_home))
    return ares_home


def test_import_hermes_mock_db(temp_ares_env, tmp_path, monkeypatch):
    """Test importing Hermes sessions and messages from a mock SQLite database."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    hermes_db_file = hermes_dir / "state.db"
    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))

    # Create mock Hermes schema and data
    conn = sqlite3.connect(str(hermes_db_file))
    conn.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT,
            title TEXT,
            model TEXT,
            cwd TEXT,
            started_at REAL,
            ended_at REAL,
            message_count INTEGER,
            tool_call_count INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            git_branch TEXT,
            git_repo_root TEXT,
            display_name TEXT,
            chat_id TEXT,
            chat_type TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            tool_name TEXT,
            tool_calls TEXT,
            timestamp REAL,
            token_count INTEGER,
            finish_reason TEXT,
            reasoning_content TEXT,
            active INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        INSERT INTO sessions (id, source, title, model, cwd, started_at, message_count)
        VALUES ('sess-123', 'cli', 'ARES Architecture Discussion', 'qwen3.6:35b', '/Users/dev/ARES', 1700000000.0, 2)
    """)
    conn.execute("""
        INSERT INTO messages (id, session_id, role, content, timestamp, token_count)
        VALUES
        ('m-1', 'sess-123', 'user', 'We decided to use FastAPI for the controller and keep memory in ~/.ares/memory.', 1700000001.0, 20),
        ('m-2', 'sess-123', 'assistant', 'Understood. That maintains clean boundaries.', 1700000002.0, 10)
    """)
    conn.commit()
    conn.close()

    res = import_hermes(batch_id="test-batch-1")
    assert res["skipped"] is False
    assert res["imported_conversations"] == 1
    assert res["imported_messages"] == 2


def test_filter_and_distill_facts():
    """Test heuristic extraction of preferences, decisions, projects, and loops."""
    raw_items = [
        {"source": "claude_code", "text": "ok"},
        {"source": "claude_code", "text": "ls -la"},
        {
            "source": "claude_code",
            "text": "I prefer concise responses with direct code solutions and no boilerplate.",
        },
        {
            "source": "hermes",
            "text": "Decision: We decided to standardize on local-first GGUF and MLX models.",
        },
        {
            "source": "codex",
            "text": "Currently working on project: ARES Multi-Agent Cross-Sync.",
        },
        {
            "source": "ares_journal",
            "text": "Need to fix blocker: UI state synchronization race condition in webui.",
        },
    ]

    filtered = filter_high_signal_items(raw_items)
    assert len(filtered) == 4

    facts = distill_facts_from_corpus(filtered)
    assert any("concise" in f["text"].lower() or "boilerplate" in f["text"].lower() for f in facts["preferences"])
    assert any("standardize" in f["text"].lower() or "gguf" in f["text"].lower() for f in facts["decisions"])
    assert any("ares" in f["text"].lower() for f in facts["projects"])
    assert any("blocker" in f["text"].lower() or "race condition" in f["text"].lower() for f in facts["open_loops"])


def test_sync_cross_agent_memory_flow(temp_ares_env, tmp_path, monkeypatch):
    """Test full end-to-end sync, JSON creation, and Markdown generation."""
    claude_dir = tmp_path / ".claude"
    proj_dir = claude_dir / "projects" / "proj-1"
    proj_dir.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_HOME", str(claude_dir))

    transcript_file = proj_dir / "transcript.jsonl"
    transcript_file.write_text(json.dumps({
        "type": "user",
        "content": "Always use pytest for automated verification. Our project is ARES.",
    }) + chr(10))

    res = sync_cross_agent_memory(limit=50, distill=True)
    assert res["status"] == "success"
    assert res["raw_items_ingested"] >= 1

    person_json = temp_ares_env / "memory" / "person.json"
    person_md = temp_ares_env / "memory" / "person.md"
    assert person_json.exists()
    assert person_md.exists()

    profile_data = get_cross_agent_profile()
    assert "profile" in profile_data
    assert "# Personal Profile & Cross-Agent Memory" in profile_data["markdown"]

    status = get_cross_agent_status()
    assert status["available_sources"]["claude_code"]["available"] is True


def test_fastapi_cross_agent_routes(temp_ares_env):
    """Test FastAPI memory router endpoints."""
    from fastapi_app.main import app

    client = TestClient(app)

    # Status
    resp = client.get("/api/memory/cross-agent/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "available_sources" in data

    # Sync
    resp = client.post("/api/memory/cross-agent/sync?limit=50&distill=true")
    assert resp.status_code == 200
    sync_res = resp.json()
    assert sync_res["status"] == "success"

    # Profile
    resp = client.get("/api/memory/cross-agent/profile")
    assert resp.status_code == 200
    prof = resp.json()
    assert "profile" in prof
    assert "markdown" in prof
