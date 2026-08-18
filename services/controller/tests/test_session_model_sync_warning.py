"""``POST /api/session/update`` must surface a JaegerAI model-sync failure.

Before this fix, ``sync_main_model_to_jaeger`` swallowed the failure to
``None`` and the session was left showing the picked model/provider as if it
had taken, even though JaegerAI's own config was never updated and kept
serving the previous model. This is the mechanical cause behind a picker
selection silently failing over with no visible sign anything went wrong.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.models import Session
from fastapi_app.main import create_app
from fastapi_app.realtime import RealtimeService
from fastapi_app.request_context import (
    RequestIdentity,
    require_identity,
    require_mutation_identity,
)


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        frontend_root=tmp_path / "missing-dist",
        realtime_service=RealtimeService(adapter_registry=None),
    )
    identity = RequestIdentity(session_cookie=None, profile="default", auth_enabled=False)
    app.dependency_overrides[require_identity] = lambda: identity
    app.dependency_overrides[require_mutation_identity] = lambda: identity
    return TestClient(app)


def test_update_session_reports_model_sync_warning_on_jaeger_rejection(monkeypatch, tmp_path):
    session = Session(
        session_id="pick_local_model",
        profile="default",
        workspace=str(tmp_path),
        model="qwen3.6:35b-mlx",
        model_provider="local",
        messages=[],
    )
    monkeypatch.setattr("api.models.get_session", lambda *_a, **_k: session)
    monkeypatch.setattr(
        "api.session_mutations.update_session_execution_lane",
        lambda *_a, **_k: session,
    )
    monkeypatch.setattr(
        "api.backend_selector.get_active_backend",
        lambda *_a, **_k: "jaeger_local",
    )
    monkeypatch.setattr("api.config.get_config", lambda: {})
    monkeypatch.setattr(
        "api.model_catalog.sync_main_model_to_jaeger",
        lambda *_a, **_k: {"ok": False, "error": "Jaeger could not resolve local model 'qwen3.6:35b-mlx'"},
    )
    monkeypatch.setattr(session, "save", lambda *a, **k: None)

    response = _client(tmp_path).post(
        "/api/session/update",
        json={"session_id": session.session_id, "model": "qwen3.6:35b-mlx", "model_provider": "local"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "qwen3.6:35b-mlx" in body["model_sync_warning"]


def test_update_session_omits_warning_when_sync_succeeds(monkeypatch, tmp_path):
    session = Session(
        session_id="pick_cloud_model",
        profile="default",
        workspace=str(tmp_path),
        model="qwen3.5:397b",
        model_provider="ollama-cloud",
        messages=[],
    )
    monkeypatch.setattr("api.models.get_session", lambda *_a, **_k: session)
    monkeypatch.setattr(
        "api.session_mutations.update_session_execution_lane",
        lambda *_a, **_k: session,
    )
    monkeypatch.setattr(
        "api.backend_selector.get_active_backend",
        lambda *_a, **_k: "jaeger_local",
    )
    monkeypatch.setattr("api.config.get_config", lambda: {})
    monkeypatch.setattr(
        "api.model_catalog.sync_main_model_to_jaeger",
        lambda *_a, **_k: {"ok": True},
    )
    monkeypatch.setattr(session, "save", lambda *a, **k: None)

    response = _client(tmp_path).post(
        "/api/session/update",
        json={"session_id": session.session_id, "model": "qwen3.5:397b", "model_provider": "ollama-cloud"},
    )

    assert response.status_code == 200
    assert "model_sync_warning" not in response.json()
