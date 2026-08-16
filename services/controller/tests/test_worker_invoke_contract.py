"""Contract tests for the worker-invocation seam in ``api.chat_runtime``.

Stream targets are invoked by convention across four modules whose signatures
drift independently. A keyword the target does not declare raises TypeError
*inside* the worker thread, where ``Thread.start()`` has already returned
success — so the caller reports HTTP 200 with a live ``stream_id`` while the
thread is already dead and the UI waits on a stream that never emits. These
tests pin the three defenses against that: kwargs filtering, a real fallback
registry, and a boot-error event that reaches the stream.
"""
from __future__ import annotations

import logging
import threading

import pytest

from api.chat_runtime import (
    FALLBACK_BACKEND_IDS,
    USER_TEXT_ALIASES,
    _filter_kwargs_for_callable,
    _publish_worker_boot_error,
)

TURN_KWARGS = {
    "model_provider": "openai",
    "goal_related": False,
    "user_text": "hi",
    "original_message": "hi",
    "user_message": "hi",
}


# ── kwargs filtering ─────────────────────────────────────────────────────────


def test_filter_drops_kwargs_the_target_cannot_accept():
    def jaeger_shaped(session_id, msg, *, model_provider=None, goal_related=False, user_text=None):
        return None

    bound = _filter_kwargs_for_callable(jaeger_shaped, TURN_KWARGS)

    assert set(bound) == {"model_provider", "goal_related", "user_text"}
    assert "original_message" not in bound
    assert "user_message" not in bound


def test_filtered_call_does_not_raise_type_error():
    """The exact regression: a target without ``original_message``."""
    called: dict = {}

    def jaeger_shaped(session_id, msg, *, model_provider=None, goal_related=False, user_text=None):
        called["user_text"] = user_text

    bound = _filter_kwargs_for_callable(jaeger_shaped, TURN_KWARGS)
    jaeger_shaped("sid", "prompt", **bound)  # must not raise

    assert called["user_text"] == "hi"


def test_filter_passes_everything_through_to_var_keyword_targets():
    def permissive(session_id, msg, **kwargs):
        return None

    assert _filter_kwargs_for_callable(permissive, TURN_KWARGS) == TURN_KWARGS


def test_filter_warns_only_on_unexpected_drift(caplog):
    """Alias drops are routine; an unknown dropped keyword is real drift."""

    def only_aliases_dropped(session_id, msg, *, model_provider=None, goal_related=False, user_text=None):
        return None

    with caplog.at_level(logging.WARNING, logger="api.chat_runtime"):
        _filter_kwargs_for_callable(only_aliases_dropped, TURN_KWARGS)
    assert caplog.records == []

    def drops_a_real_contract_key(session_id, msg, *, user_text=None):
        return None

    with caplog.at_level(logging.WARNING, logger="api.chat_runtime"):
        _filter_kwargs_for_callable(drops_a_real_contract_key, TURN_KWARGS)
    assert any("model_provider" in record.getMessage() for record in caplog.records)


def test_every_stream_target_accepts_at_least_one_user_text_alias():
    """History purity depends on the typed text reaching each worker."""
    import inspect

    targets = [
        ("api.providers.jaeger.gateway_streaming", "run_jros_streaming"),
        ("api.providers.hermes.streaming", "run_hermes_streaming"),
        ("api.gateway_chat", "_run_gateway_chat_streaming"),
        ("api.providers.agentic_backend", "run_agentic_backend_streaming"),
    ]
    for module_name, attr in targets:
        target = getattr(__import__(module_name, fromlist=[attr]), attr)
        names = set(inspect.signature(target).parameters)
        assert names & USER_TEXT_ALIASES, f"{attr} accepts no user-text alias"


@pytest.mark.parametrize(
    "module_name,attr",
    [
        ("api.providers.jaeger.gateway_streaming", "run_jros_streaming"),
        ("api.providers.hermes.streaming", "run_hermes_streaming"),
        ("api.gateway_chat", "_run_gateway_chat_streaming"),
        ("api.providers.agentic_backend", "run_agentic_backend_streaming"),
    ],
)
def test_real_stream_targets_bind_the_canonical_turn_kwargs(module_name, attr):
    """Guards P0 directly: every shipped target must bind a real turn call."""
    import inspect

    target = getattr(__import__(module_name, fromlist=[attr]), attr)
    bound = _filter_kwargs_for_callable(target, TURN_KWARGS)
    inspect.signature(target).bind(
        "session-id", "context-wrapped prompt", "model", "/tmp/ws", "stream-id", [], **bound
    )


# ── fallback registry ────────────────────────────────────────────────────────


def test_fallback_ids_all_exist_in_the_worker_registry():
    """``hermes_proxy``/``claude_cloud`` matched nothing and silently
    routed turns to Ollama."""
    from api.backends.router import get_default_router

    registry = set(get_default_router().backends)
    unknown = [name for name in FALLBACK_BACKEND_IDS if name not in registry]
    assert not unknown, f"fallback ids missing from the registry: {unknown}"


def test_fallback_order_prefers_local_assistants():
    assert FALLBACK_BACKEND_IDS[0] == "jaeger_local"
    assert "hermes_local" in FALLBACK_BACKEND_IDS


# ── worker boot errors ───────────────────────────────────────────────────────


class _RecordingChannel:
    def __init__(self) -> None:
        self.items: list = []

    def put_nowait(self, item) -> None:
        self.items.append(item)


def test_boot_error_publishes_an_error_event_on_the_stream(monkeypatch):
    from api import chat_runtime

    channel = _RecordingChannel()
    monkeypatch.setitem(chat_runtime.STREAMS, "stream-1", channel)

    _publish_worker_boot_error("stream-1", "session-1", TypeError("boom"))

    names = [item[0] for item in channel.items]
    assert names[0] == "error"
    assert "stream_end" in names
    payload = channel.items[0][1]
    assert payload["type"] == "worker_boot_failed"
    assert "boom" in payload["message"]
    # The stream must not stay registered, or status probes report it live.
    assert "stream-1" not in chat_runtime.STREAMS


def test_thread_wrapper_shape_turns_a_dying_target_into_an_error_event(monkeypatch):
    """End-to-end shape of the wrapper installed in ``start_session_turn``."""
    from api import chat_runtime

    channel = _RecordingChannel()
    monkeypatch.setitem(chat_runtime.STREAMS, "stream-2", channel)

    def exploding_target(*args, **kwargs):
        raise TypeError("got an unexpected keyword argument 'original_message'")

    def _thread_main() -> None:
        try:
            exploding_target()
        except Exception as exc:
            chat_runtime._publish_worker_boot_error("stream-2", "session-2", exc)

    thread = threading.Thread(target=_thread_main, daemon=True)
    thread.start()
    thread.join(5)

    assert not thread.is_alive()
    assert [item[0] for item in channel.items][0] == "error"
