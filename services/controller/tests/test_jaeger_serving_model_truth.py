"""ARES reports the model that answered, not the one it asked for.

JaegerAI picks its serving lane at boot and can end up somewhere else
than its config requests — a cloud lane that fails to start leaves
``external_model.enabled: true`` in the file while a local model answers.
ARES showing the requested model in that state tells the operator they
are on a cloud brain when they are not, which is precisely the failure
they cannot see through.

So ARES asks the bridge (``serving_model``) and records the answer. The
query is cached, because the serving lane is fixed at boot and this runs
on every turn's writeback; and it can never raise, because a display
value must not be able to fail a turn.
"""

import api.providers.jaeger.streaming as gs


CLOUD = {
    "name": "qwen3.5:397b",
    "provider": "ollama-cloud",
    "location": "cloud",
    "context_length": 262_144,
    "serving": True,
    "fallback_active": False,
    "status": "serving now — this is the model answering",
}


def _reset():
    gs.reset_serving_model_cache()


def test_serving_truth_is_read_from_the_bridge(monkeypatch):
    _reset()
    monkeypatch.setattr(
        gs, "query_local_companion",
        lambda what, args=None: {"booted": True, "serving": CLOUD})
    row = gs._serving_model_truth()
    assert row["name"] == "qwen3.5:397b"
    assert row["context_length"] == 262_144


def test_pre_boot_is_not_cached_as_truth(monkeypatch):
    """Before a client exists JaegerAI reports its intent with
    ``booted: False``. Caching that would pin "unknown" for the whole TTL
    and the first real turn would still show nothing."""
    _reset()
    calls = []

    def _pre_boot(what, args=None):
        calls.append(what)
        return {"booted": False, "serving": None, "configured": {}}

    monkeypatch.setattr(gs, "query_local_companion", _pre_boot)
    assert gs._serving_model_truth() is None
    assert gs._serving_model_truth() is None
    assert len(calls) == 2, "a pre-boot answer was cached as if it were truth"


def test_result_is_cached_across_turns(monkeypatch):
    _reset()
    calls = []

    def _once(what, args=None):
        calls.append(what)
        return {"booted": True, "serving": CLOUD}

    monkeypatch.setattr(gs, "query_local_companion", _once)
    gs._serving_model_truth()
    gs._serving_model_truth()
    gs._serving_model_truth()
    assert len(calls) == 1


def test_a_reboot_invalidates_the_cached_lane(monkeypatch):
    """``reset_jaeger_runtime()`` is what runs after a model switch. The lane
    is fixed at boot, so a re-boot must drop what we cached about it or
    ARES keeps reporting the previous model."""
    _reset()
    monkeypatch.setattr(
        gs, "query_local_companion",
        lambda what, args=None: {"booted": True, "serving": CLOUD})
    assert gs._serving_model_truth()["name"] == "qwen3.5:397b"

    switched = dict(CLOUD, name="deepseek-v4-pro:0813", context_length=1_048_576)
    monkeypatch.setattr(
        gs, "query_local_companion",
        lambda what, args=None: {"booted": True, "serving": switched})
    # Still cached...
    assert gs._serving_model_truth()["name"] == "qwen3.5:397b"
    gs.reset_serving_model_cache()
    assert gs._serving_model_truth()["name"] == "deepseek-v4-pro:0813"


def test_an_unreachable_bridge_never_raises(monkeypatch):
    _reset()

    def _boom(what, args=None):
        raise RuntimeError("bridge not started")

    monkeypatch.setattr(gs, "query_local_companion", _boom)
    assert gs._serving_model_truth() is None


def test_a_garbage_answer_is_ignored(monkeypatch):
    _reset()
    for payload in (None, "nope", 42, {}, {"serving": "not-a-dict"}):
        monkeypatch.setattr(
            gs, "query_local_companion", lambda what, args=None, p=payload: p)
        gs.reset_serving_model_cache()
        assert gs._serving_model_truth() is None


def test_fallback_state_survives_the_round_trip(monkeypatch):
    """The flag that matters most: cloud requested, local answering."""
    _reset()
    fell_back = {
        "name": "gemma-4-E4B-it-Q4_K_M",
        "provider": "mlx",
        "location": "local",
        "context_length": 8192,
        "serving": True,
        "fallback_active": True,
        "requested": "ollama-cloud/deepseek-v4-pro:0813",
        "status": "serving now — FALLBACK: ollama-cloud/deepseek-v4-pro:0813 "
                  "was configured but mlx/gemma-4-E4B-it-Q4_K_M is answering",
    }
    monkeypatch.setattr(
        gs, "query_local_companion",
        lambda what, args=None: {"booted": True, "serving": fell_back})
    row = gs._serving_model_truth()
    assert row["fallback_active"] is True
    assert "deepseek-v4-pro:0813" in row["requested"]
