"""Regression coverage for the shared Ollama provider lane."""

from pathlib import Path

from api.ares_provider_sync import (
    JROS_FALLBACK_PROVIDER_MAP,
    PROVIDER_PRESETS,
    load_yaml_config,
    sync_provider,
    provider_runtime_status,
)
def test_ollama_launch_is_a_local_provider_alias():
    assert PROVIDER_PRESETS["ollama-launch"]["base_url"].endswith("/v1")
    assert JROS_FALLBACK_PROVIDER_MAP["ollama-launch"] == "ollama"


def test_provider_status_distinguishes_installed_from_running():
    status = provider_runtime_status("ollama-launch", "http://127.0.0.1:1/v1")
    assert status["available"] is False
    assert status["state"] in {"installed_not_running", "not_installed"}


def test_sync_ollama_launch_persists_ares_and_commands_jaeger(tmp_path: Path, monkeypatch):
    ares = tmp_path / "config.yaml"
    ares.write_text("model:\n  default: old\n", encoding="utf-8")
    captured = {}
    monkeypatch.setattr(
        "api.providers.jaeger.gateway_streaming.command_local_companion",
        lambda command, payload: captured.update(command=command, payload=payload) or {
            "changed": False, "restart_required": False},
    )
    result = sync_provider(
        "ollama-launch",
        "gemma4",
        targets=["ares", "jros"],
        ares_config_path=ares,
    )
    assert result["ok"] is True
    ares_cfg = load_yaml_config(ares)
    assert ares_cfg["model"]["provider"] == "ollama-launch"
    assert ares_cfg["model"]["default"] == "gemma4"
    assert captured["command"] == "configure_model"
    assert captured["payload"]["provider"] == "ollama"
    assert captured["payload"]["model"] == "gemma4"
    assert captured["payload"]["base_url"].endswith("/v1")
