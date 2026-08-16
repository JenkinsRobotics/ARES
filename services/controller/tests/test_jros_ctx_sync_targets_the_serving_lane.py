"""Which JaegerAI config key a synced context window lands in.

JaegerAI keeps two windows and they mean different things:

  - ``model.ctx`` sizes the LOCAL lane — the llama.cpp/MLX KV cache that
    gets allocated on boot;
  - ``external_model.ctx`` describes the window of a CLOUD model, which
    costs this machine nothing.

The sync wrote the resolved window to BOTH. That was invisible while
every model resolved to 131072, but the moment a real probe returns
``deepseek-v4-pro:0813``'s 1048576 it becomes an instruction to allocate
a 1M-token KV cache on a local 27B model. It also mattered the other
way: ``external_model.ctx`` had no schema field on the Jaeger side, so
writing it made the instance config fail validation outright.
"""

import api.ares_provider_sync as sync


BASE_CONFIG = {
    "instance_name": "jarvis",
    "model": {"ctx": 131_072, "model_path": "/models/qwen3.6-27b-5bit"},
    "external_model": {"enabled": True, "provider": "ollama-cloud",
                       "model": "deepseek-v4-pro:0813"},
}


def _sync(monkeypatch, provider, model, window):
    monkeypatch.setattr(
        "api.model_context.resolve_context_length_for_session_model",
        lambda *a, **k: window,
    )
    return sync._sync_jros_config(BASE_CONFIG, provider, model, None, None)


def test_a_cloud_window_never_resizes_the_local_kv_cache(monkeypatch):
    out = _sync(monkeypatch, "ollama-cloud", "deepseek-v4-pro:0813", 1_048_576)
    assert out["external_model"]["ctx"] == 1_048_576
    assert out["model"]["ctx"] == 131_072, (
        "a cloud model's window was written into the local lane — the next "
        "boot would try to allocate a 1M-token KV cache"
    )


def test_a_local_model_configures_the_local_lane(monkeypatch):
    out = _sync(monkeypatch, "local", "qwen3.6-27b-5bit", 32_768)
    assert out["model"]["ctx"] == 32_768
    # The cloud lane keeps whatever it had; this sync says nothing about it.
    assert "ctx" not in out["external_model"] or \
        out["external_model"].get("ctx") != 32_768


def test_an_unresolvable_window_leaves_both_lanes_alone(monkeypatch):
    """Better a stale-but-real number than overwriting it with a guess of
    zero — and the failure gets logged rather than swallowed."""
    out = _sync(monkeypatch, "ollama-cloud", "mystery-model", 0)
    assert out["model"]["ctx"] == 131_072
    assert "ctx" not in out["external_model"]


def test_a_resolver_explosion_does_not_break_the_sync(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr(
        "api.model_context.resolve_context_length_for_session_model", _boom)
    out = sync._sync_jros_config(
        BASE_CONFIG, "ollama-cloud", "deepseek-v4-pro:0813", None, None)
    # Model selection still syncs; only the window is missing.
    assert out["external_model"]["model"] == "deepseek-v4-pro:0813"
    assert out["model"]["ctx"] == 131_072
