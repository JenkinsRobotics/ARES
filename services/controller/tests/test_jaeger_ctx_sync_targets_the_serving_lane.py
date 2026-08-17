"""ARES sends model context to Jaeger without editing Jaeger configuration."""

from api.ares_provider_sync import sync_provider


def test_context_window_is_sent_to_jaeger_configure_command(monkeypatch):
    captured = {}
    monkeypatch.setattr("api.model_context.resolve_context_length_for_session_model", lambda *a, **k: 1_048_576)
    monkeypatch.setattr(
        "api.providers.jaeger.streaming.command_local_companion",
        lambda name, payload: captured.update(name=name, payload=payload) or {"changed": False},
    )
    sync_provider("ollama-cloud", "deepseek-v4-pro:0813", targets=["jaeger"], dry_run=True)
    assert captured["name"] == "configure_model"
    assert captured["payload"]["context_length"] == 1_048_576
    assert captured["payload"]["dry_run"] is True


def test_context_resolution_failure_does_not_break_bridge_request(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    captured = {}
    monkeypatch.setattr("api.model_context.resolve_context_length_for_session_model", boom)
    monkeypatch.setattr(
        "api.providers.jaeger.streaming.command_local_companion",
        lambda name, payload: captured.update(payload) or {"changed": False},
    )
    sync_provider("openai", "gpt-4o", targets=["jaeger"], dry_run=True)
    assert captured["context_length"] is None
