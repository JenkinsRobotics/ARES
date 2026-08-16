"""Context windows come from the provider, not from a keyword guess.

`_estimate_model_context_length` answers by substring — anything matching
"deepseek" gets 131072. Ollama publishes the real number on `/api/show`
(`model_info["<arch>.context_length"]`), and for `deepseek-v4-pro:0813`
that number is 1048576: an 8x undercount that silently caps compaction
thresholds, the WebUI context ring, and the `ctx` ARES syncs into
JaegerAI's config.

Two failures are pinned here:

  - the probe itself — parsing, name variants, cloud-vs-local ordering,
    and the rule that a probe never raises into a turn;
  - resolver precedence — an optional missing dependency used to abort
    the whole resolution and discard the operator's OWN configured
    window, because `from agent.model_metadata import …` was the first
    statement inside one big `try`.
"""

import api.model_context as model_context
import api.providers.ollama.context_probe as probe


# ── payload parsing ────────────────────────────────────────────────


def test_window_is_read_from_the_architecture_prefixed_key():
    """Real `/api/show` bodies key the window by architecture, so match
    on the suffix instead of enumerating architectures."""
    assert probe._context_length_from_payload(
        {"model_info": {"deepseek4.context_length": 1_048_576,
                        "general.architecture": "deepseek4"}}
    ) == 1_048_576


def test_window_falls_back_to_details_then_bare_key():
    """`/api/tags` rows and older daemons use the other two shapes."""
    assert probe._context_length_from_payload(
        {"details": {"context_length": 262_144}}) == 262_144
    assert probe._context_length_from_payload({"context_length": 8192}) == 8192


def test_unparseable_payloads_report_no_opinion():
    for payload in (None, {}, "nope", {"model_info": {}},
                    {"model_info": {"x.context_length": "huge"}},
                    {"details": {"context_length": 0}}):
        assert probe._context_length_from_payload(payload) == 0


# ── name variants ──────────────────────────────────────────────────


def test_local_variants_cover_both_cloud_tag_spellings():
    """A pulled cloud model is tagged locally, and the spelling depends on
    whether the id already carries a tag: `glm-5.2` is stored as
    `glm-5.2:cloud`, `deepseek-v4-pro:0813` as `…:0813-cloud`."""
    assert probe._local_name_variants("glm-5.2") == ["glm-5.2", "glm-5.2:cloud"]
    assert probe._local_name_variants("deepseek-v4-pro:0813") == [
        "deepseek-v4-pro:0813", "deepseek-v4-pro:0813-cloud"]
    # Already tagged as cloud — nothing to add.
    assert probe._local_name_variants("glm-5.2:cloud") == ["glm-5.2:cloud"]


def test_cloud_variants_strip_the_local_cloud_marker():
    """ollama.com knows the plain id, not the local cloud tag."""
    assert probe._cloud_name_variants("glm-5.2:cloud") == ["glm-5.2:cloud", "glm-5.2"]
    assert probe._cloud_name_variants("deepseek-v4-pro:0813-cloud") == [
        "deepseek-v4-pro:0813-cloud", "deepseek-v4-pro:0813"]


# ── probe behaviour ────────────────────────────────────────────────


def test_cloud_provider_is_asked_before_the_local_daemon(monkeypatch):
    """A cloud id is usually unknown to the local daemon, so spending a
    timeout there first would add latency to every resolution."""
    probe.reset_cache()
    asked: list[str] = []

    def _fake_show(base, model, *, timeout, api_key=""):
        asked.append(base)
        return 1_048_576 if "ollama.com" in base else 0

    monkeypatch.setattr(probe, "_post_show", _fake_show)
    monkeypatch.setattr(probe, "_cloud_api_key", lambda *a, **k: "key")
    monkeypatch.setattr(probe, "installed_context_lengths", dict)

    assert probe.context_length(
        "deepseek-v4-pro:0813", provider="ollama-cloud") == 1_048_576
    assert asked[0] == probe.CLOUD_API_BASE


def test_local_models_never_reach_for_the_network(monkeypatch):
    probe.reset_cache()
    monkeypatch.setattr(
        probe, "installed_context_lengths", lambda: {"mistral:7b": 32_768})

    def _explode(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("a local hit must not trigger an HTTP probe")

    monkeypatch.setattr(probe, "_post_show", _explode)
    assert probe.context_length("mistral:7b", provider="ollama") == 32_768


def test_allow_cloud_false_keeps_the_probe_on_device(monkeypatch):
    probe.reset_cache()
    monkeypatch.setattr(probe, "installed_context_lengths", dict)
    monkeypatch.setattr(probe, "_post_show", lambda *a, **k: 0)
    monkeypatch.setattr(
        probe, "_cloud_api_key",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("phoned out")))
    assert probe.context_length(
        "x", provider="ollama-cloud", allow_cloud=False) == 0


def test_results_are_cached_including_misses(monkeypatch):
    """A stopped daemon must cost one timeout per TTL, not one per turn."""
    probe.reset_cache()
    calls: list[str] = []

    def _count(*a, **k):
        calls.append("x")
        return 0

    monkeypatch.setattr(probe, "installed_context_lengths", dict)
    monkeypatch.setattr(probe, "_post_show", _count)
    monkeypatch.setattr(probe, "_cloud_api_key", lambda *a, **k: "")
    probe.context_length("ghost", provider="ollama")
    first = len(calls)
    probe.context_length("ghost", provider="ollama")
    assert len(calls) == first, "a cached miss re-probed the provider"


def test_a_broken_provider_never_raises_into_a_turn(monkeypatch):
    probe.reset_cache()

    def _boom(*a, **k):
        raise OSError("connection reset")

    monkeypatch.setattr(probe, "installed_context_lengths", _boom)
    monkeypatch.setattr(probe, "_post_show", _boom)
    monkeypatch.setattr(probe, "_cloud_api_key", lambda *a, **k: "")
    # The dispatcher is the contract boundary: it absorbs anything.
    assert model_context._probe_provider_context_length("m", "ollama") == 0


def test_non_ollama_providers_are_not_probed(monkeypatch):
    """`/v1/models` carries no window, so there is nothing to ask an
    OpenAI-compatible provider for — don't spend a round trip finding out."""
    monkeypatch.setattr(
        probe, "context_length",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("probed")))
    for provider in ("anthropic", "openai", "xai", "gemini"):
        assert model_context._probe_provider_context_length("m", provider) == 0


def test_session_probe_keeps_ollama_cloud_as_cloud(monkeypatch):
    """The chat-tab ring reads session.context_length, which goes through
    ``_probe_provider_context_length``. That helper used to run
    ``normalize_provider_id("ollama-cloud")`` → ``""`` → ``"ollama"``
    and ask the local daemon first."""
    seen: list[str] = []

    def _capture(model, *, provider=None, api_key=None):
        seen.append(provider)
        return 1_048_576

    monkeypatch.setattr(probe, "context_length", _capture)
    assert model_context._probe_provider_context_length(
        "deepseek-v4-pro:0813", "ollama-cloud") == 1_048_576
    assert seen == ["ollama-cloud"]


def test_jaeger_local_uses_the_serving_lane_window(monkeypatch):
    """A Jaeger worker session is not an Ollama model family. The ring
    must show the window of the model Jaeger is actually running."""
    monkeypatch.setattr(
        "api.providers.jaeger.active_model.active_model",
        lambda: {
            "model": "qwen3.5:397b",
            "provider": "ollama-cloud",
            "ctx": 131_072,
        },
    )
    monkeypatch.setattr(
        probe, "context_length",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("probed")),
    )
    assert model_context._probe_provider_context_length(
        "qwen3.5:397b", "jaeger_local") == 131_072


def test_jaeger_local_probes_the_serving_provider_when_ctx_is_missing(monkeypatch):
    seen: list[tuple[str, str]] = []

    def _capture(model, *, provider=None, api_key=None):
        seen.append((model, provider))
        return 262_144

    monkeypatch.setattr(
        "api.providers.jaeger.active_model.active_model",
        lambda: {
            "model": "kimi-k2:1t",
            "provider": "ollama-cloud",
            "ctx": None,
        },
    )
    monkeypatch.setattr(probe, "context_length", _capture)
    assert model_context._probe_provider_context_length(
        "ignored", "jaeger_local") == 262_144
    assert seen == [("kimi-k2:1t", "ollama-cloud")]


# ── resolver precedence ────────────────────────────────────────────


def _no_agent_package(monkeypatch):
    """The optional metadata package is absent on plenty of installs —
    including every ARES box without the agent checkout."""
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("agent"):
            raise ModuleNotFoundError("No module named 'agent'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)


def test_configured_window_survives_a_missing_agent_package(monkeypatch):
    """The regression: the `agent.model_metadata` import was the first
    statement of the `try` that also built the config lookup, so a
    missing optional dependency threw away the operator's explicit
    setting and answered with the keyword guess instead."""
    cfg = {"providers": {"ollama-cloud": {
        "models": {"deepseek-v4-pro:0813": {"context_length": 163_840}}}}}
    monkeypatch.setattr("api.config.get_config", lambda *a, **k: cfg)
    monkeypatch.setattr(
        model_context, "_probe_provider_context_length", lambda *a, **k: 999)
    _no_agent_package(monkeypatch)

    assert model_context.resolve_context_length_for_session_model(
        "deepseek-v4-pro:0813", "ollama-cloud") == 163_840


def test_ollama_cloud_probe_beats_bundled_metadata(monkeypatch):
    """The chat ring used to show 128k for qwen3.5:397b because a
    bundled family table (or the keyword guess) answered first. The
    live ``/api/show`` window is 256k."""
    monkeypatch.setattr("api.config.get_config", lambda *a, **k: {})
    monkeypatch.setattr(
        model_context, "_probe_provider_context_length",
        lambda *a, **k: 262_144)

    def _stale_table(*a, **k):
        return 131_072

    import sys
    import types
    fake = types.ModuleType("agent.model_metadata")
    fake.get_model_context_length = _stale_table
    monkeypatch.setitem(sys.modules, "agent.model_metadata", fake)
    agent_pkg = types.ModuleType("agent")
    agent_pkg.model_metadata = fake
    monkeypatch.setitem(sys.modules, "agent", agent_pkg)

    assert model_context.resolve_context_length_for_session_model(
        "qwen3.5:397b", "ollama-cloud") == 262_144


def test_probe_beats_the_keyword_guess(monkeypatch):
    monkeypatch.setattr("api.config.get_config", lambda *a, **k: {})
    monkeypatch.setattr(
        model_context, "_probe_provider_context_length",
        lambda *a, **k: 1_048_576)
    _no_agent_package(monkeypatch)

    resolved = model_context.resolve_context_length_for_session_model(
        "deepseek-v4-pro:0813", "ollama-cloud")
    assert resolved == 1_048_576
    # The live probe is what must win; the keyword guess now also
    # knows V4 is 1M, so pick a family whose estimate still differs.
    monkeypatch.setattr(
        model_context, "_probe_provider_context_length",
        lambda *a, **k: 262_144)
    qwen = model_context.resolve_context_length_for_session_model(
        "qwen3.5:397b", "ollama-cloud")
    assert qwen == 262_144
    assert qwen != model_context._estimate_model_context_length(
        "qwen3.5:397b", "ollama-cloud")


def test_keyword_guess_remains_the_last_resort(monkeypatch):
    """With no config, no metadata package and a silent provider, an
    answer is still better than none — the ring needs a number."""
    monkeypatch.setattr("api.config.get_config", lambda *a, **k: {})
    monkeypatch.setattr(
        model_context, "_probe_provider_context_length", lambda *a, **k: 0)
    _no_agent_package(monkeypatch)

    assert model_context.resolve_context_length_for_session_model(
        "deepseek-v4-pro:0813", "ollama-cloud") == 1_048_576


def test_an_empty_model_resolves_to_nothing():
    assert model_context.resolve_context_length_for_session_model("") == 0
    assert model_context.resolve_context_length_for_session_model(None) == 0


def test_session_update_defines_model_was_set_before_jaeger_sync():
    """Picking DeepSeek in the chat tab never reached Jaeger: the
    handler referenced ``model_was_set`` without assigning it, so the
    sync was swallowed and the ring got context_length=0."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "fastapi_app" / "routers" / "session.py"
    text = src.read_text(encoding="utf-8")
    assign = text.find('model_was_set = "model" in fields')
    use = text.find("if model_was_set or provider_was_set:")
    assert assign != -1 and use != -1 and assign < use


def test_jaeger_describe_config_exposes_the_serving_ctx():
    """The chat ring / session resolver read this ``ctx`` so they do
    not have to re-guess a window Jaeger already wrote."""
    from api.providers.jaeger.active_model import describe_config

    cloud = describe_config({
        "model": {"ctx": 8192, "model_path": "/models/local.gguf"},
        "external_model": {
            "enabled": True, "provider": "ollama-cloud",
            "model": "qwen3.5:397b", "ctx": 131_072,
        },
    })
    assert cloud["provider"] == "ollama-cloud"
    assert cloud["ctx"] == 131_072

    local = describe_config({
        "model": {"ctx": 32_768, "model_path": "/models/local.gguf"},
        "external_model": {"enabled": False},
    })
    assert local["provider"] == "local"
    assert local["ctx"] == 32_768
