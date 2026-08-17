from api.characters import list_characters, get_character
from api.model_catalog import sync_main_model_to_jaeger


def test_characters_api(monkeypatch):
    rows = [{
        "id": "assistant_char",
        "name": "Assistant Character",
        "role": "Assistant",
        "voice_tone": "Neutral",
        "level": 3,
        "revision": 2.0,
        "custom_instructions": "Be helpful.",
        "backstory": "Test backstory.",
        "speech_patterns": ["Pattern 1"],
        "traits": {
            "hexaco": {"Honesty": 4},
            "special": {"IQ": 130},
            "expression": {"Happy": True},
            "domains": ["General"],
        },
        "lore": {
            "quotes": ["Hello"],
            "mannerisms": ["Nodding"],
            "ideals": ["Helpfulness"],
            "behaviors": ["Polite"],
        },
    }, {
        "id": "basic_char",
        "name": "Basic Character",
    }]
    monkeypatch.setattr("api.characters._query", lambda what, args=None: rows if what == "characters" else next((r for r in rows if r["id"] == (args or {}).get("id")), None))

    # Test list_characters
    chars = list_characters()
    assert len(chars) == 2
    char_ids = {c["id"] for c in chars}
    assert char_ids == {"assistant_char", "basic_char"}

    # Test get_character (valid)
    char1 = get_character("assistant_char")
    assert char1 is not None
    assert char1["id"] == "assistant_char"
    assert char1["name"] == "Assistant Character"
    assert char1["description"] == "Assistant"
    assert char1["role"] == "Assistant"
    assert char1["voice_tone"] == "Neutral"
    assert char1["level"] == 3
    assert char1["revision"] == 2.0
    assert char1["traits"]["hexaco"] == {"Honesty": 4}
    assert char1["traits"]["special"] == {"IQ": 130}
    assert char1["traits"]["expression"] == {"Happy": True}
    assert char1["traits"]["domains"] == ["General"]
    assert char1["lore"]["quotes"] == ["Hello"]
    assert char1["lore"]["mannerisms"] == ["Nodding"]
    assert char1["lore"]["ideals"] == ["Helpfulness"]
    assert char1["lore"]["behaviors"] == ["Polite"]
    assert char1["custom_instructions"] == "Be helpful."
    assert char1["backstory"] == "Test backstory."
    assert char1["speech_patterns"] == ["Pattern 1"]

    # Test get_character (defaults checked)
    char2 = get_character("basic_char")
    assert char2 is not None
    assert char2["id"] == "basic_char"
    assert char2["name"] == "Basic Character"
    assert char2["description"] == ""
    assert char2["role"] == ""
    assert char2["voice_tone"] == ""
    assert char2["level"] == 1
    assert char2["revision"] == 1.0
    assert char2["lore"]["quotes"] == []
    assert char2["custom_instructions"] == ""

    # Test get_character (non-existent)
    char_none = get_character("nonexistent_char")
    assert char_none is None


def test_sync_main_model_to_jaeger_success(monkeypatch):
    called_sync = []
    called_reset = []

    def mock_sync_provider(provider, model, targets, ares_config_path):
        called_sync.append((provider, model, targets, ares_config_path))

    def mock_reset_jaeger_runtime():
        called_reset.append(True)

    monkeypatch.setattr("api.ares_provider_sync.sync_provider", mock_sync_provider)
    monkeypatch.setattr("api.providers.jaeger.streaming.reset_jaeger_runtime", mock_reset_jaeger_runtime)
    monkeypatch.setattr("api.model_catalog.active_profile_config_path", lambda: "/path/to/ares/config.yaml")

    # Call with a model mapped in JaegerAI_FALLBACK_PROVIDER_MAP (e.g. "openai")
    # Result contains "provider" and "model"
    sync_main_model_to_jaeger({"provider": "openai", "model": "gpt-4o"})

    assert len(called_sync) == 1
    # "openai" maps to "openai" in JaegerAI_FALLBACK_PROVIDER_MAP
    assert called_sync[0] == ("openai", "gpt-4o", ["jaeger"], "/path/to/ares/config.yaml")
    assert len(called_reset) == 1


def test_sync_main_model_to_jaeger_no_mapping(monkeypatch):
    called_sync = []
    called_reset = []

    def mock_sync_provider(provider, model, targets, ares_config_path):
        called_sync.append((provider, model, targets, ares_config_path))

    def mock_reset_jaeger_runtime():
        called_reset.append(True)

    monkeypatch.setattr("api.ares_provider_sync.sync_provider", mock_sync_provider)
    monkeypatch.setattr("api.providers.jaeger.streaming.reset_jaeger_runtime", mock_reset_jaeger_runtime)
    monkeypatch.setattr("api.model_catalog.active_profile_config_path", lambda: "/path/to/ares/config.yaml")

    # Call with an unmapped provider
    sync_main_model_to_jaeger({"provider": "unknown-provider", "model": "some-model"})

    # Should skip sync
    assert len(called_sync) == 0
    assert len(called_reset) == 0


def test_sync_main_model_to_jaeger_handles_exception(monkeypatch):
    called_reset = []

    def mock_sync_provider_fail(provider, model, targets, ares_config_path):
        raise RuntimeError("Sync failed")

    def mock_reset_jaeger_runtime():
        called_reset.append(True)

    monkeypatch.setattr("api.ares_provider_sync.sync_provider", mock_sync_provider_fail)
    monkeypatch.setattr("api.providers.jaeger.streaming.reset_jaeger_runtime", mock_reset_jaeger_runtime)
    monkeypatch.setattr("api.model_catalog.active_profile_config_path", lambda: "/path/to/ares/config.yaml")

    # Should not raise exception
    sync_main_model_to_jaeger({"provider": "openai", "model": "gpt-4o"})
    # Should not call reset_jaeger_runtime if sync failed
    assert len(called_reset) == 0


def test_characters_list_api_endpoint_handles_unavailable_jaeger(monkeypatch):
    from fastapi.testclient import TestClient
    from fastapi_app.main import create_app

    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: False)
    monkeypatch.setattr("api.characters._query", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    with TestClient(create_app()) as client:
        response = client.get("/api/ares/characters")

    assert response.status_code == 200
    assert response.json()["characters"] == []


def test_character_detail_api_endpoint_handles_unavailable_jaeger(monkeypatch):
    from fastapi.testclient import TestClient
    from fastapi_app.main import create_app

    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: False)
    monkeypatch.setattr("api.characters._query", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    with TestClient(create_app()) as client:
        response = client.get("/api/ares/character?id=test-character")

    assert response.status_code == 404
    assert response.json()["error"] == "Character not found"
