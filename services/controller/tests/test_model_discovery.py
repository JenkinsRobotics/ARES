"""Model/provider discovery through owner APIs."""

from __future__ import annotations

from api.backends.model_discovery import (
    discover_jaeger_models,
    list_jaeger_installed_gguf,
    list_ollama_cloud_models,
    list_ollama_local_models,
    list_ollama_registered_cloud_models,
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
    assert isinstance(list_ollama_cloud_models(), list)
    assert isinstance(list_jaeger_installed_gguf(), list)


def test_ollama_catalogs_separate_local_cloud_and_embeddings(monkeypatch):
    payload = {
        "models": [
            {"name": "local-agent", "capabilities": ["completion", "tools"]},
            {
                "name": "cloud-agent:cloud",
                "remote_host": "https://ollama.com",
                "capabilities": ["completion", "tools"],
            },
            {"name": "embedding", "capabilities": ["embedding"]},
        ]
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            import json

            return json.dumps(payload).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    assert [row["id"] for row in list_ollama_local_models()] == ["local-agent"]
    assert [row["id"] for row in list_ollama_registered_cloud_models()] == ["cloud-agent:cloud"]
