"""Behavioral contracts for the Jaeger production path.

These tests lock the five user-visible promises against the real
``JaegerBackend`` object and the real ``_run_local_jaeger_turn`` exception
path. Fake backends with ``is_gateway=True`` are not proof.

Promises:
  1. Multi-turn memory: production Jaeger is a gateway; turn 2 is the new
     user text, not a serialized transcript.
  2. Sessions survive worker eviction: the next turn hydrates with
     ``load_session`` resume=True.
  3. Tools remain available: the same live session id is reused; hydrate
     restores JaegerAgent.messages after a new bridge process.
  4. Successful requests produce no hidden exceptions: telemetry on a
     successful reply does not fail the turn or evict the client.
  5. Production configuration uses the intended gateway path:
     ``JaegerBackend.get_worker_target()[1] is True``.
"""
from __future__ import annotations

import threading
from api import chat_runtime
from api.chat_runtime import start_session_turn
from api.providers.jaeger.backend import JaegerBackend
from api.providers.jaeger.streaming import run_jaeger_streaming
from tests.test_chat_runtime import _isolate_runtime, _session


def test_production_jaeger_backend_selects_gateway_path():
    worker, is_gateway, is_jaeger = JaegerBackend().get_worker_target()
    assert worker is run_jaeger_streaming
    assert is_gateway is True
    assert is_jaeger is True


def test_production_jaeger_multi_turn_sends_clean_user_text(monkeypatch):
    session = _session()
    session.messages = [
        {"role": "user", "content": "the app is Apple Mail"},
        {"role": "assistant", "content": "I listed your folders"},
    ]
    _isolate_runtime(monkeypatch, session)
    captured = []

    def fake_streaming(*args, **kwargs):
        captured.append((args, kwargs))

    monkeypatch.setattr(
        "api.providers.jaeger.streaming.run_jaeger_streaming",
        fake_streaming,
    )

    class ImmediateThread:
        def __init__(self, *, target, args, kwargs, **_rest):
            self.target, self.args, self.kwargs = target, args, kwargs

        def start(self):
            self.target(*self.args, **self.kwargs)

    monkeypatch.setattr("api.chat_runtime.threading.Thread", ImmediateThread)
    backend = JaegerBackend()

    first = start_session_turn(
        session.session_id, "reorganize the folders in the app",
        source="webui", backend=backend,
    )
    assert first.get("_status") != 409
    session.active_stream_id = None
    chat_runtime.STREAMS.pop(first.get("stream_id"), None)
    second = start_session_turn(
        session.session_id, "delete the Harbor Freight mail",
        source="webui", backend=backend,
    )
    assert second.get("_status") != 409

    assert len(captured) == 2
    first_prompt = captured[0][0][1]
    second_prompt = captured[1][0][1]
    assert first_prompt == "reorganize the folders in the app"
    assert second_prompt == "delete the Harbor Freight mail"
    assert "Previous conversation" not in first_prompt
    assert "Previous conversation" not in second_prompt
    assert "Apple Mail" not in second_prompt


def test_successful_turn_with_telemetry_does_not_fail_or_evict(monkeypatch):
    from api.providers.jaeger import streaming

    evicted = []

    class Client:
        def is_alive(self):
            return True

        def close(self):
            return None

        def query(self, what, args=None):
            return []

        def turn(self, text, **_kwargs):
            return {
                "text": "listed folders",
                "error": None,
                "elapsed_s": 1.25,
                "ctx_used": 4096,
                "halt_reason": None,
            }

    monkeypatch.setattr(streaming, "_jaeger_instance_name", lambda: "test")
    monkeypatch.setattr(streaming, "_get_or_start_bridge_client", lambda _instance: Client())
    monkeypatch.setattr(
        streaming, "_evict_bridge_client",
        lambda *args, **kwargs: evicted.append(args),
    )
    streaming.STREAM_TURN_TELEMETRY.clear()
    streaming._HYDRATED_SESSIONS.clear()

    text, error, _activity = streaming._run_local_jaeger_turn(
        "list folders", "session-mail", "/tmp/workspace",
        threading.Event(), stream_id="stream-1",
    )

    assert text == "listed folders"
    assert error == ""
    assert evicted == []
    assert streaming.STREAM_TURN_TELEMETRY["stream-1"]["elapsed_s"] == 1.25
    assert streaming.STREAM_TURN_TELEMETRY["stream-1"]["ctx_used"] == 4096


def test_bookkeeping_error_after_success_does_not_evict(monkeypatch):
    from api.providers.jaeger import streaming

    evicted = []

    class Client:
        def turn(self, text, **_kwargs):
            return {"text": "ok", "error": None, "elapsed_s": 0.5}

        def query(self, *_args, **_kwargs):
            return []

    monkeypatch.setattr(streaming, "_jaeger_instance_name", lambda: "test")
    monkeypatch.setattr(streaming, "_get_or_start_bridge_client", lambda _instance: Client())
    monkeypatch.setattr(
        streaming, "_evict_bridge_client",
        lambda *args, **kwargs: evicted.append(args),
    )
    monkeypatch.setattr(
        streaming, "_record_turn_telemetry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("telemetry boom")),
    )
    streaming._HYDRATED_SESSIONS.clear()

    text, error, _activity = streaming._run_local_jaeger_turn(
        "hello", "session-1", "/tmp/workspace", threading.Event(),
        stream_id="stream-boom",
    )

    assert text == "ok"
    assert error == ""
    assert evicted == []


def test_dead_bridge_evicts_but_does_not_replay_turn(monkeypatch):
    from api.providers.jaeger import streaming

    calls = []
    evicted = []

    class Client:
        def query(self, *_args, **_kwargs):
            return []

        def turn(self, text, **_kwargs):
            calls.append(text)
            raise BrokenPipeError(32, "broken pipe")

    monkeypatch.setattr(streaming, "_jaeger_instance_name", lambda: "test")
    monkeypatch.setattr(streaming, "_get_or_start_bridge_client", lambda _instance: Client())
    real_evict = streaming._evict_bridge_client

    def tracking_evict(*args, **kwargs):
        evicted.append(True)
        return real_evict(*args, **kwargs)

    monkeypatch.setattr(streaming, "_evict_bridge_client", tracking_evict)
    streaming._HYDRATED_SESSIONS.clear()
    streaming._BRIDGE_CLIENTS.clear()

    text, error, _activity = streaming._run_local_jaeger_turn(
        "hello", "session-1", "/tmp/workspace", threading.Event(),
    )

    assert text == ""
    assert "broken pipe" in error
    assert calls == ["hello"]
    assert evicted == [True]


def test_next_turn_after_eviction_hydrates_with_resume(monkeypatch):
    from api.providers.jaeger import streaming

    queries = []

    class Client:
        def query(self, what, args=None):
            queries.append((what, dict(args or {})))
            return [{"role": "user", "text": "the app is Apple Mail"}]

        def turn(self, text, **_kwargs):
            return {"text": "ok", "error": None}

    client = Client()
    monkeypatch.setattr(streaming, "_jaeger_instance_name", lambda: "test")
    monkeypatch.setattr(streaming, "_get_or_start_bridge_client", lambda _instance: client)
    streaming._HYDRATED_SESSIONS.clear()

    streaming._run_local_jaeger_turn(
        "first", "ebc26ecd4af3", "/tmp/ws", threading.Event(),
    )
    streaming._run_local_jaeger_turn(
        "second", "ebc26ecd4af3", "/tmp/ws", threading.Event(),
    )
    assert queries == [
        ("load_session", {"id": "ebc26ecd4af3", "resume": True}),
    ]

    streaming._evict_bridge_client("test", client)
    streaming._run_local_jaeger_turn(
        "third", "ebc26ecd4af3", "/tmp/ws", threading.Event(),
    )
    assert queries == [
        ("load_session", {"id": "ebc26ecd4af3", "resume": True}),
        ("load_session", {"id": "ebc26ecd4af3", "resume": True}),
    ]


def test_display_load_does_not_resume_live_agent(monkeypatch):
    from api.session_contract import runtime_query

    seen = {}

    def fake_query(what, args=None):
        seen["what"] = what
        seen["args"] = dict(args or {})
        return []

    monkeypatch.setattr(
        "api.providers.jaeger.streaming.query_local_companion",
        fake_query,
    )
    runtime_query("load", session_id="ebc26ecd4af3")
    assert seen["what"] == "load_session"
    assert seen["args"]["resume"] is False


def test_malformed_turn_payload_does_not_raise():
    from api.providers.jaeger import streaming

    streaming._record_turn_telemetry("s", {"elapsed_s": "not-a-problem", "ctx_used": 1})
    assert streaming.STREAM_TURN_TELEMETRY["s"]["ctx_used"] == 1
