from pathlib import Path

from fastapi.testclient import TestClient
import pytest
import yaml

from api.ares_provider_sync import sync_fallback_chain, sync_provider
from fastapi_app.main import create_app
from fastapi_app.request_context import RequestIdentity, require_mutation_identity
from fastapi_app.routers.onboarding import require_onboarding_mutation


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture(autouse=True)
def _pinned_context_window(monkeypatch):
    """Keep bridge payloads independent of the operator's model catalog."""
    monkeypatch.setattr(
        "api.model_context.resolve_context_length_for_session_model",
        lambda *args, **kwargs: 128_000,
    )


def test_sync_updates_ares_and_routes_jaeger_through_bridge(tmp_path, monkeypatch):
    ares_config = tmp_path / "ares" / "config.yaml"
    _write_yaml(ares_config, {"model": {"provider": "openai", "default": "gpt-4o"}, "ui": {"theme": "dark"}})
    captured = {}

    def command(name, payload):
        captured.update(name=name, payload=payload)
        return {"ok": True, "changed": True, "restart_required": True}

    monkeypatch.setattr("api.providers.jaeger.streaming.command_local_companion", command)
    monkeypatch.setattr("api.providers.jaeger.streaming.reset_jaeger_runtime", lambda: None)
    monkeypatch.setattr("api.model_context.resolve_context_length_for_session_model", lambda *a, **k: 128_000)

    result = sync_provider("gemini", "gemini-2.5-pro", targets=["ares", "jaeger"], ares_config_path=ares_config)

    assert set(result["changed_targets"]) == {"ares", "jaeger"}
    assert result["targets"]["jaeger"] == {"owner": "jaeger", "changed": True, "restart_required": True}
    assert captured == {"name": "configure_model", "payload": {
        "provider": "gemini", "model": "gemini-2.5-pro",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "context_length": 128_000, "dry_run": False,
    }}
    ares = yaml.safe_load(ares_config.read_text())
    assert ares["ui"] == {"theme": "dark"}


def test_explicit_jaeger_config_path_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Jaeger owns its configuration"):
        sync_provider("gemini", "gemini-2.5-pro", targets=["jaeger"], jaeger_config_path=tmp_path / "config.yaml")


def test_unsupported_provider_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unsupported provider"):
        sync_provider("not-a-provider", "model", targets=["ares"], ares_config_path=tmp_path / "config.yaml")


def test_provider_sync_route_lives_in_handle_post_not_handle_get():
    with TestClient(create_app()) as client:
        response = client.get("/api/ares/provider/sync")
    assert response.status_code == 404


def test_provider_sync_route_requires_onboarding_gate_when_auth_disabled(monkeypatch):
    app = create_app()
    app.dependency_overrides[require_mutation_identity] = lambda: RequestIdentity(None, None, False)
    monkeypatch.setattr("api.network_trust.onboarding_gate_allows", lambda *args: False)
    with TestClient(app) as client:
        response = client.post("/api/ares/provider/sync", json={"provider": "gemini", "model": "gemini-2.5-pro"})
    assert response.status_code == 403


def test_provider_sync_post_route_calls_sync_provider(monkeypatch, tmp_path):
    captured = {}

    def fake_sync_provider(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "changed_targets": ["ares"]}

    app = create_app()
    app.dependency_overrides[require_onboarding_mutation] = lambda: RequestIdentity(None, None, False)
    monkeypatch.setattr("api.config._get_config_path", lambda: tmp_path / "ares" / "config.yaml")
    monkeypatch.setattr("api.ares_provider_sync.sync_provider", fake_sync_provider)
    with TestClient(app) as client:
        response = client.post("/api/ares/provider/sync", json={
            "provider": "gemini", "model": "gemini-2.5-pro", "targets": ["ares"], "dry_run": True})
    assert response.status_code == 200
    assert captured["targets"] == ["ares"]


def test_fallback_chain_is_not_written_into_jaeger(tmp_path):
    ares_config = tmp_path / "ares" / "config.yaml"
    _write_yaml(ares_config, {"fallback_providers": [{"provider": "ollama-cloud", "model": "glm-4.7"}]})
    result = sync_fallback_chain(ares_config_path=ares_config)
    assert result["fallback_chain_synced"] is False
    assert result["targets"]["jaeger"]["owner"] == "jaeger"
    assert result["targets"]["jaeger"]["supported"] is False
    assert result["changed_targets"] == []


def test_fallback_chain_sync_no_fallback_chain(tmp_path):
    ares_config = tmp_path / "ares" / "config.yaml"
    _write_yaml(ares_config, {"model": {"provider": "openai"}})
    result = sync_fallback_chain(ares_config_path=ares_config)
    assert result["targets"]["ares"]["note"] == "no fallback chain"
