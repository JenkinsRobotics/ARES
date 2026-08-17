"""Model/provider discovery through owner APIs."""

from __future__ import annotations

from api.backends.model_discovery import (
    discover_jaeger_models,
    list_jaeger_installed_gguf,
    list_ollama_local_models,
)


def test_discover_jaeger_models_uses_bridge_catalog(monkeypatch):
    monkeypatch.setattr(
        "api.providers.jaeger.streaming.query_local_companion",
        lambda query, _payload: {
            "models": [{"id": "model-1", "location": "local", "in_use": True}],
            "providers": [{"id": "local"}],
            "serving": {"model": "model-1", "provider": "local"},
        },
    )
    discovered = discover_jaeger_models()
    models = discovered.get("models") or []
    assert any(m.get("id") == "model-1" for m in models)
    assert any(m.get("in_use") for m in models)
    for m in models:
        assert not str(m.get("id") or "").startswith("(")


def test_list_helpers_do_not_raise():
    assert isinstance(list_ollama_local_models(), list)
    assert isinstance(list_jaeger_installed_gguf(), list)
