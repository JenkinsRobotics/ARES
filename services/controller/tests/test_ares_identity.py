import api.ares_identity as identity
import api.persona as persona_api


def test_persona_names_apply_only_to_the_elected_jaeger_runtime(monkeypatch):
    def fake_load_persona(persona_id):
        assert persona_id == "anakin"
        return {"identity": {"display_name": "Anakin Skywalker"}, "name": "Anakin"}

    monkeypatch.setattr(persona_api, "load_persona", fake_load_persona)
    monkeypatch.setattr(identity, "_jaeger_live_display_name", lambda: None)
    monkeypatch.setattr(identity, "_jaeger_default_agent_name", lambda: None)

    unselected = identity.build_identity_payload(
        bot_name="Astra", backend="", persona_id="anakin"
    )
    jaeger = identity.build_identity_payload(
        bot_name="Astra", backend="jaeger", persona_id="anakin"
    )
    assert unselected["display_name"] == "Astra"
    assert unselected["identity_kind"] == "default"
    assert jaeger["display_name"] == "Anakin Skywalker"
    assert jaeger["identity_kind"] == "character"


def test_incomplete_setup_uses_neutral_product_fallback(monkeypatch):
    monkeypatch.setattr(identity, "_jaeger_live_display_name", lambda: None)
    monkeypatch.setattr(identity, "_jaeger_default_agent_name", lambda: None)

    payload = identity.build_identity_payload(bot_name="Ares", backend="jaeger")

    assert payload["display_name"] == "ARES Assistant"
    assert payload["default_display_name"] == "ARES Assistant"


def test_backend_badges_describe_external_runtime_selection(monkeypatch):
    monkeypatch.setattr(identity, "_jaeger_live_display_name", lambda: None)
    monkeypatch.setattr(identity, "_jaeger_default_agent_name", lambda: None)

    assert "Jaeger AI" in identity.get_backend_badge_html("jaeger")
    assert "No runtime selected" in identity.get_backend_badge_html("ares")


def test_profile_label_still_overrides_default_assistant(monkeypatch):
    monkeypatch.setattr(identity, "_jaeger_live_display_name", lambda: None)
    monkeypatch.setattr(identity, "_jaeger_default_agent_name", lambda: None)

    payload = identity.build_identity_payload(
        profile="robotics", bot_name="Astra", backend="jaeger", persona_id="anakin"
    )

    assert payload["display_name"] == "Robotics"


def test_jaeger_character_beats_ares_bot_name(monkeypatch):
    """The chat header used identity.yaml / ARES bot_name ('Jarvis')
    while Jaeger was bound to Anakin. The live display_name wins."""
    monkeypatch.setattr(
        identity, "_jaeger_live_display_name", lambda: "Anakin Skywalker")
    payload = identity.build_identity_payload(
        bot_name="Jarvis", backend="jaeger")
    assert payload["display_name"] == "Anakin Skywalker"


def test_live_jaeger_name_wins_even_when_backend_slug_is_missing(monkeypatch):
    monkeypatch.setattr(
        identity, "_jaeger_live_display_name", lambda: "Anakin Skywalker")
    payload = identity.build_identity_payload(
        bot_name="Jarvis", backend="")
    assert payload["display_name"] == "Anakin Skywalker"


def test_live_character_id_beats_stale_instance_display_name(monkeypatch):
    def fake_query(what, args=None):
        assert what == "identity"
        return {
            "agent_name": "Jarvis",
            "display_name": "Jarvis",
            "character": "Jarvis",
            "character_id": "anakin",
        }

    monkeypatch.setattr(
        "api.providers.jaeger.streaming.query_local_companion", fake_query)
    monkeypatch.setattr(
        identity, "_persona_display_name", lambda pid: "Anakin Skywalker" if pid == "anakin" else None)
    assert identity._jaeger_live_display_name() == "Anakin Skywalker"
