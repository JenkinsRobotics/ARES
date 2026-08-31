"""Hot-path boundaries for the compact per-turn ARES runtime context."""

from __future__ import annotations

from api import ares_runtime_context as runtime_context


def _isolate_context(monkeypatch):
    monkeypatch.setattr(
        runtime_context,
        "_identity_projection_for_backend",
        lambda backend: {"name": backend or "none"},
    )
    monkeypatch.setattr(
        "api.ares_devices.device_config",
        lambda _config: {
            "ai_id": "ares-main",
            "role": "primary",
            "device_id": "test-mac",
            "device_name": "Test Mac",
            "primary_device_id": "test-mac",
            "primary_url": "",
        },
    )
    monkeypatch.setattr("api.config.get_config", lambda: {})


def test_non_jaeger_turn_does_not_probe_jaeger(monkeypatch):
    _isolate_context(monkeypatch)
    from api.providers.jaeger import status

    def unexpected_probe():
        raise AssertionError("a non-Jaeger turn must not probe the Jaeger bridge")

    status.reset_cache()
    monkeypatch.setattr(status, "_uncached_status", unexpected_probe)

    context = runtime_context.build_runtime_context(backend="ollama_local")

    assert context["active_backend"] == "ollama_local"
    assert context["embodiment"]["jaeger_connected"] is False


def test_turn_context_uses_static_device_identity_not_fleet_health(monkeypatch):
    _isolate_context(monkeypatch)
    monkeypatch.setattr(runtime_context, "is_jaeger_available", lambda: False)

    def unexpected_health(_config):
        raise AssertionError("per-turn context must not run a full device health audit")

    monkeypatch.setattr("api.ares_devices.device_status", unexpected_health)

    context = runtime_context.build_runtime_context(backend="ollama_local")

    assert context["device"] == {
        "ai_id": "ares-main",
        "role": "primary",
        "is_primary": True,
        "device_id": "test-mac",
        "device_name": "Test Mac",
        "primary": {"device_id": "test-mac", "url": ""},
    }


def test_jaeger_turn_uses_cached_availability_boundary(monkeypatch):
    _isolate_context(monkeypatch)
    calls = []
    monkeypatch.setattr(
        runtime_context,
        "is_jaeger_available",
        lambda: calls.append("probe") or True,
    )

    context = runtime_context.build_runtime_context(backend="jaeger_local")

    assert calls == ["probe"]
    assert context["embodiment"]["jaeger_connected"] is True
