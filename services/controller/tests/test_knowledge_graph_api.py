"""Tests for Knowledge Graph extraction and RAG folder management APIs."""

import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from api.knowledge_graph import (
    _get_rag_sources,
    _resolve_knowledge_folders,
    build_knowledge_graph,
    read_knowledge_document,
)
from fastapi_app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def temp_vault(tmp_path):
    vault = tmp_path / "TestVault"
    vault.mkdir()

    doc1 = vault / "Agent_Architecture.md"
    doc1.write_text("""# Agent Architecture
This is the core architecture note for #robotics and #agents.
References [[ARES_Gateway]] and [[Hardware_Interface]].
""", encoding="utf-8")

    doc2 = vault / "ARES_Gateway.md"
    doc2.write_text("""# ARES Gateway
Connects to [[Agent_Architecture]] and #streaming.
""", encoding="utf-8")

    sub = vault / "Hardware"
    sub.mkdir()
    doc3 = sub / "Hardware_Interface.md"
    doc3.write_text("""# Hardware Interface
Controls actuators and links to [[Agent_Architecture]].
""", encoding="utf-8")

    return vault


def test_build_knowledge_graph(temp_vault):
    graph = build_knowledge_graph(sources=[str(temp_vault)], max_nodes=50)
    assert graph["ok"] is True
    assert len(graph["nodes"]) == 3
    assert len(graph["links"]) >= 2
    assert "robotics" in graph["tags"]
    assert "Hardware" in graph["clusters"] or "General" in graph["clusters"]

    node_ids = {n["id"] for n in graph["nodes"]}
    assert "agent_architecture" in node_ids
    assert "ares_gateway" in node_ids
    assert "hardware_interface" in node_ids


def test_missing_config_does_not_invent_a_developer_specific_source(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert _get_rag_sources() == []


def test_configured_folder_is_not_silently_rewritten_to_named_child(tmp_path):
    configured = tmp_path / "vault"
    configured.mkdir()
    (configured / "03_Knowledge").mkdir()

    assert _resolve_knowledge_folders([str(configured)]) == [configured]


def test_read_knowledge_document(temp_vault):
    doc1 = temp_vault / "Agent_Architecture.md"
    res = read_knowledge_document(str(doc1))
    assert res["ok"] is True
    assert res["title"] == "Agent Architecture"
    assert "core architecture note" in res["content"]


def test_knowledge_graph_api_endpoint(client, temp_vault, monkeypatch):
    monkeypatch.setattr("api.knowledge_graph._get_rag_sources", lambda: [{"path": str(temp_vault)}])
    response = client.get("/api/knowledge/graph")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["nodes"]) >= 3


def test_knowledge_document_api_endpoint(client, temp_vault):
    doc1 = temp_vault / "ARES_Gateway.md"
    response = client.get(f"/api/knowledge/document?path={doc1}")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["file_name"] == "ARES_Gateway.md"
