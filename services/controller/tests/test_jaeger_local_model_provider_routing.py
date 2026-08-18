"""A locally-installed Ollama model must sync through the "ollama" provider.

JaegerAI's own catalog tags a model reachable through the local Ollama
daemon with ``provider: "ollama"`` (it configures those the same way it
configures Ollama Cloud, just pointed at localhost) — distinct from a raw
GGUF/MLX file its filesystem registry resolves directly. Collapsing both
into ARES's hardcoded ``"local"`` provider sent Ollama-served local picks
through JaegerAI's raw-file resolver, which can't find them (they were never
a bare file on disk) and rejected the pick outright, even though the model
was fully installed and reachable. Reproduces the exact failure this session
found live: ``qwen3.6:35b-mlx``, a real, fully-downloaded Ollama model.
"""

from __future__ import annotations

from api.model_catalog import _get_jaeger_local_models


def test_ollama_served_local_model_keeps_ollama_provider(monkeypatch):
    monkeypatch.setattr(
        "api.backends.model_discovery.list_jaeger_installed_gguf",
        lambda: [
            {
                "id": "qwen3.6:35b-mlx",
                "label": "qwen3.6:35b-mlx",
                "location": "local",
                "provider": "ollama",
                "source": "ollama",
            }
        ],
    )

    models = _get_jaeger_local_models()

    assert len(models) == 1
    assert models[0]["provider"] == "ollama"
    assert models[0]["provider_id"] == "ollama"


def test_raw_registry_gguf_model_keeps_local_provider(monkeypatch):
    monkeypatch.setattr(
        "api.backends.model_discovery.list_jaeger_installed_gguf",
        lambda: [
            {
                "id": "gemma-4-e4b-it-q4_k_m",
                "label": "gemma-4-e4b-it-q4_k_m",
                "location": "local",
                "provider": "in-process",
                "source": "registry",
            }
        ],
    )

    models = _get_jaeger_local_models()

    assert len(models) == 1
    assert models[0]["provider"] == "local"
    assert models[0]["provider_id"] == "local"


def test_missing_provider_field_defaults_to_local(monkeypatch):
    monkeypatch.setattr(
        "api.backends.model_discovery.list_jaeger_installed_gguf",
        lambda: [{"id": "some-model", "location": "local"}],
    )

    models = _get_jaeger_local_models()

    assert models[0]["provider"] == "local"
