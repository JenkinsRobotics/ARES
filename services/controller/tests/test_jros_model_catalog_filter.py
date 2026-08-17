from __future__ import annotations

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


def test_non_jros_backend_keeps_full_model_catalog(monkeypatch):
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


def test_jros_backend_shows_only_real_compatible_model_providers(monkeypatch):
    from api import backend_selector, model_catalog

    monkeypatch.setattr("api.config.get_config", lambda: {"ares_backend": "jaeger_local"})
    monkeypatch.setattr(backend_selector, "get_active_backend", lambda config: config["ares_backend"])

    result = model_catalog.filter_catalog_for_active_backend(_catalog(), enrich=False)

    assert [g["provider_id"] for g in result["groups"]] == [
        "ollama-cloud",
        "ollama-local",
    ]
    assert "jros" not in [g["provider_id"] for g in result["groups"]]
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


def test_jros_backend_enriches_available_models(monkeypatch):
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
