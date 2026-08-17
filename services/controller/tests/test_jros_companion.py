"""Companion onboarding uses Jaeger's bridge contract exclusively."""

import pytest


def _fake_local_jros_root(root, monkeypatch):
    from api.providers.jaeger import companion

    monkeypatch.setattr(companion, "local_jros_root", lambda: root)


def test_companion_availability_uses_install_resolver(monkeypatch, tmp_path):
    from api.providers.jaeger import companion

    _fake_local_jros_root(None, monkeypatch)
    assert companion.companion_available() is False
    _fake_local_jros_root(tmp_path, monkeypatch)
    assert companion.companion_available() is True


def test_setup_defaults_and_exists_are_bridge_queries(monkeypatch):
    from api.providers.jaeger import companion

    calls = []

    def query(name, args):
        calls.append((name, args))
        if name == "instance_exists":
            return {"exists": True}
        return {"characters": [{"id": "alpha", "name": "Alpha"}]}

    monkeypatch.setattr(
        "api.providers.jaeger.gateway_streaming.query_local_companion", query)
    assert companion.companion_exists() is True
    assert companion.list_characters() == [{"id": "alpha", "name": "Alpha"}]
    assert calls == [("instance_exists", {}), ("setup_defaults", {})]


def test_companion_exists_fails_closed(monkeypatch):
    from api.providers.jaeger import companion

    monkeypatch.setattr(
        "api.providers.jaeger.gateway_streaming.query_local_companion",
        lambda *args: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert companion.companion_exists() is False


def test_create_companion_is_bridge_command(monkeypatch):
    from api.providers.jaeger import companion

    captured = {}
    monkeypatch.setattr(
        "api.providers.jaeger.gateway_streaming.command_local_companion",
        lambda command, payload: captured.update(command=command, payload=payload) or {
            "instance": "alpha-agent", "root": "/runtime/alpha-agent"},
    )

    result = companion.create_companion(
        character_id="alpha",
        display_name="Alpha",
        role="Assistant",
        voice_id="voice-1",
        awake_model="awake-model",
        asleep_model="asleep-model",
        make_default=False,
    )

    assert result == {
        "ok": True, "name": "alpha-agent",
        "instance_dir": "/runtime/alpha-agent", "owner": "jaeger"}
    assert captured["command"] == "create_instance"
    assert captured["payload"]["character_id"] == "alpha"
    assert captured["payload"]["display_name"] == "Alpha"
    assert captured["payload"]["role"] == "Assistant"
    assert captured["payload"]["awake_model"] == "awake-model"
    assert captured["payload"]["asleep_model"] == "asleep-model"
    assert captured["payload"]["make_default"] is False


def test_blank_character_uses_runtime_roster(monkeypatch):
    from api.providers.jaeger import companion

    monkeypatch.setattr(companion, "list_characters", lambda: [{"id": "alpha"}])
    captured = {}
    monkeypatch.setattr(
        "api.providers.jaeger.gateway_streaming.command_local_companion",
        lambda command, payload: captured.update(payload) or {"instance": "a", "root": "/a"},
    )
    companion.create_companion(character_id="default")
    assert captured["character_id"] == "alpha"


def test_blank_character_fails_when_roster_is_empty(monkeypatch):
    from api.providers.jaeger import companion

    monkeypatch.setattr(companion, "list_characters", lambda: [])
    with pytest.raises(ValueError, match="No characters are installed"):
        companion.create_companion(character_id="")
