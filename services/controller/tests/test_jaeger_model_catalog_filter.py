from __future__ import annotations

import pytest

def _catalog():
    return {
        "active_provider": "xai-oauth",
        "default_model": "grok-4.3",
        "configured_model_badges": {
            "grok-4.3": {"provider": "xai-oauth"},
            "glm-5.1": {"provider": "ollama-cloud"},
            "gemma4:e4b-mlx": {"provider": "ollama-local"},
            "gpt-5.5": {"provider": "openai-codex"},
        },
        "groups": [
            {"provider": "XAI", "provider_id": "xai-oauth", "models": [{"id": "grok-4.3", "label": "Grok"}]},
            {"provider": "Ollama Cloud", "provider_id": "ollama-cloud", "models": [{"id": "glm-5.1", "label": "GLM"}]},
            {"provider": "Ollama Local", "provider_id": "ollama-local", "models": [{"id": "gemma4:e4b-mlx", "label": "Gemma"}]},
            {"provider": "Codex", "provider_id": "openai-codex", "models": [{"id": "gpt-5.5", "label": "GPT"}]},
        ],
    }


@pytest.fixture(autouse=True)
def _no_live_jaeger_config(monkeypatch):
    """Cut these tests off from the OPERATOR'S live Jaeger configuration.

    filter_catalog_for_active_backend calls discover_jaeger_models()
    directly, and derives `hide_local` from whatever provider that reports
    as the configured default. A cloud default (ollama-cloud, openai,
    anthropic, gemini, xai) strips the local and ollama groups entirely.

    So a test that mocked its model sources but not discovery still read
    ~/.ares, and its result depended on how the machine happened to be
    configured. On a box defaulted to ollama-cloud,
    test_jaeger_local_group_drops_models_the_ollama_group_already_lists
    failed with KeyError: 'ollama' — zero groups survived — while passing
    everywhere else. That is an environment leak, not a flake.

    Default to an empty discovery; tests that care set their own after
    this fixture and win, since monkeypatch applies in order.
    """
    monkeypatch.setattr(
        "api.backends.model_discovery.discover_jaeger_models",
        lambda: {}, raising=False,
    )


def test_non_jaeger_backend_keeps_full_model_catalog(monkeypatch):
    from api import backend_selector, model_catalog

    monkeypatch.setattr("api.config.get_config", lambda: {"ares_backend": "claude_local"})
    monkeypatch.setattr(backend_selector, "get_active_backend", lambda config: config["ares_backend"])

    result = model_catalog.filter_catalog_for_active_backend(_catalog())

    assert [g["provider_id"] for g in result["groups"]] == [
        "xai-oauth",
        "ollama-cloud",
        "ollama-local",
        "openai-codex",
    ]
    assert result["active_provider"] == "xai-oauth"
    assert result["default_model"] == "grok-4.3"


def test_jaeger_backend_shows_only_real_compatible_model_providers(monkeypatch):
    from api import backend_selector, model_catalog

    monkeypatch.setattr("api.config.get_config", lambda: {"ares_backend": "jaeger_local"})
    monkeypatch.setattr(backend_selector, "get_active_backend", lambda config: config["ares_backend"])

    result = model_catalog.filter_catalog_for_active_backend(_catalog(), enrich=False)

    assert [g["provider_id"] for g in result["groups"]] == [
        "ollama-cloud",
        "ollama-local",
    ]
    assert "jaeger" not in [g["provider_id"] for g in result["groups"]]
    assert result["active_provider"] == "ollama-cloud"
    assert result["default_model"] == "glm-5.1"
    # Only the resolved selection is badged. Badging every surviving model (the
    # old behavior) made the picker hoist the whole catalog into its flat
    # "Configured" section, leaving the provider groups empty so none of their
    # collapsible headings rendered.
    assert set(result["configured_model_badges"]) == {"glm-5.1"}
    assert result["configured_model_badges"]["glm-5.1"] == {
        "provider": "ollama-cloud",
        "role": "primary",
        "label": "Primary",
    }


def test_jaeger_backend_enriches_available_models(monkeypatch):
    from api import backend_selector, model_catalog

    monkeypatch.setattr("api.config.get_config", lambda: {"ares_backend": "jaeger_local"})
    monkeypatch.setattr(backend_selector, "get_active_backend", lambda config: config["ares_backend"])
    monkeypatch.setattr(model_catalog, "_jaeger_credential_names", lambda: {"xai_api_key"})
    monkeypatch.setattr(model_catalog, "_xai_models", lambda: [{"id": "grok-4.6", "label": "grok-4.6", "provider": "xai", "provider_id": "xai"}])
    monkeypatch.setattr(model_catalog, "_fetch_ollama_local_models", lambda: [])

    result = model_catalog.filter_catalog_for_active_backend({"groups": []}, enrich=True)

    group_ids = [g["provider_id"] for g in result["groups"]]
    assert "xai" in group_ids
    # grok-4.6 is the only discovered model, so it resolves to the default and
    # is the one entry that earns a badge.
    assert result["default_model"] == "grok-4.6"
    assert result["configured_model_badges"] == {
        "grok-4.6": {"provider": "xai", "role": "primary", "label": "Primary"}
    }


def test_jaeger_local_group_drops_models_the_ollama_group_already_lists(monkeypatch):
    """The same local Ollama daemon is discoverable two ways — ARES's own
    direct probe and JaegerAI's own catalog, which discovers it internally.
    A model reachable both ways must appear once, not twice under two
    different provider labels ("Ollama (Local)" vs "Local (Jaeger AI / MLX /
    GGUF)").
    """
    from api import backend_selector, model_catalog

    monkeypatch.setattr("api.config.get_config", lambda: {"ares_backend": "jaeger_local"})
    monkeypatch.setattr(backend_selector, "get_active_backend", lambda config: config["ares_backend"])
    monkeypatch.setattr(model_catalog, "_jaeger_credential_names", lambda: set())
    monkeypatch.setattr(
        model_catalog,
        "_fetch_ollama_local_models",
        lambda: [{"id": "qwen3.6:35b-mlx", "label": "qwen3.6:35b-mlx", "provider": "ollama", "provider_id": "ollama"}],
    )
    monkeypatch.setattr(
        model_catalog,
        "_get_jaeger_local_models",
        lambda: [
            # A duplicate of what the direct Ollama probe already found.
            {"id": "qwen3.6:35b-mlx", "label": "qwen3.6:35b-mlx", "provider": "ollama", "provider_id": "ollama"},
            # A genuinely distinct raw GGUF registry entry.
            {"id": "gemma-4-e4b-it-q4_k_m", "label": "gemma-4-e4b-it-q4_k_m", "provider": "local", "provider_id": "local"},
        ],
    )

    result = model_catalog.filter_catalog_for_active_backend({"groups": []}, enrich=True)

    groups = {g["provider_id"]: g for g in result["groups"]}
    assert [m["id"] for m in groups["ollama"]["models"]] == ["qwen3.6:35b-mlx"]
    assert [m["id"] for m in groups["local"]["models"]] == ["gemma-4-e4b-it-q4_k_m"]


def test_ollama_cloud_group_prefers_jaegers_live_catalog_over_the_curated_fallback(monkeypatch):
    """JaegerAI already live-discovers the full Ollama Cloud catalog (it holds
    the API key ARES never sees) as part of the same ``model_catalog`` bridge
    response ARES already fetches for the local-model groups. Using only a
    small hardcoded list here — when JaegerAI handed over the real one —
    is the same class of bug B4 fixed for local models.
    """
    from api import backend_selector, model_catalog

    monkeypatch.setattr("api.config.get_config", lambda: {"ares_backend": "jaeger_local"})
    monkeypatch.setattr(backend_selector, "get_active_backend", lambda config: config["ares_backend"])
    monkeypatch.setattr(model_catalog, "_jaeger_credential_names", lambda: {"ollama_cloud_api_key"})
    monkeypatch.setattr(model_catalog, "_fetch_ollama_local_models", lambda: [])
    monkeypatch.setattr(
        "api.backends.model_discovery.discover_jaeger_models",
        lambda: {
            "models": [
                {"id": "qwen3.5:397b", "label": "qwen3.5:397b", "location": "cloud", "provider": "ollama-cloud", "context_length": 131072},
                {"id": "a-brand-new-cloud-model", "label": "a-brand-new-cloud-model", "location": "cloud", "provider": "ollama-cloud", "context_length": 65536},
                {"id": "some-local-file", "label": "some-local-file", "location": "local", "provider": "in-process"},
            ],
            "providers": [],
            "default": {},
        },
    )

    result = model_catalog.filter_catalog_for_active_backend({"groups": []}, enrich=True)

    groups = {g["provider_id"]: g for g in result["groups"]}
    cloud_ids = [m["id"] for m in groups["ollama-cloud"]["models"]]
    assert cloud_ids == ["qwen3.5:397b", "a-brand-new-cloud-model"]
    assert "some-local-file" not in cloud_ids


def test_ollama_cloud_group_falls_back_to_curated_list_when_jaeger_has_nothing_live(monkeypatch):
    from api import backend_selector, model_catalog

    monkeypatch.setattr("api.config.get_config", lambda: {"ares_backend": "jaeger_local"})
    monkeypatch.setattr(backend_selector, "get_active_backend", lambda config: config["ares_backend"])
    monkeypatch.setattr(model_catalog, "_jaeger_credential_names", lambda: {"ollama_cloud_api_key"})
    monkeypatch.setattr(model_catalog, "_fetch_ollama_local_models", lambda: [])
    monkeypatch.setattr(
        "api.backends.model_discovery.discover_jaeger_models",
        lambda: {"models": [], "providers": [], "default": {}},
    )

    result = model_catalog.filter_catalog_for_active_backend({"groups": []}, enrich=True)

    groups = {g["provider_id"]: g for g in result["groups"]}
    cloud_ids = [m["id"] for m in groups["ollama-cloud"]["models"]]
    assert "qwen3.5:397b" in cloud_ids  # the curated fallback, not empty


def test_badges_mark_only_the_selection_not_the_whole_catalog(monkeypatch):
    """Regression guard for the flattened model picker.

    The web picker hoists every badged model into a single flat "Configured"
    section and drops those models from their provider groups. When the catalog
    badged all 37 models, every provider group rendered empty, so no group
    headings — and therefore no collapsible sections — appeared at all, and the
    list read as one alphabetical run of models from mixed providers.
    """
    from api import backend_selector, model_catalog

    monkeypatch.setattr("api.config.get_config", lambda: {"ares_backend": "jaeger_local"})
    monkeypatch.setattr(backend_selector, "get_active_backend", lambda config: config["ares_backend"])

    catalog = {
        "active_provider": "ollama-cloud",
        "default_model": "glm-5.1",
        "groups": [
            {
                "provider": "Ollama Cloud",
                "provider_id": "ollama-cloud",
                "models": [
                    {"id": "glm-5.1", "label": "GLM"},
                    {"id": "kimi-k3", "label": "Kimi"},
                ],
            },
            {
                "provider": "Ollama Local",
                "provider_id": "ollama-local",
                "models": [{"id": "gemma4:e4b-mlx", "label": "Gemma"}],
            },
        ],
    }

    result = model_catalog.filter_catalog_for_active_backend(catalog, enrich=False)

    badges = result["configured_model_badges"]
    assert set(badges) == {"glm-5.1"}, "only the active selection may be badged"
    assert badges["glm-5.1"]["role"] == "primary"

    # Every provider group keeps its models, so the picker still has groups to
    # render collapsible headings for.
    assert [g["provider_id"] for g in result["groups"]] == ["ollama-cloud", "ollama-local"]
    assert len(result["groups"][0]["models"]) == 2
    assert len(result["groups"][1]["models"]) == 1
