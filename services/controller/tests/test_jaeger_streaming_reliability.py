"""Failure and concurrency behavior for the canonical Jaeger stdio bridge."""

from __future__ import annotations

import threading
import time


def test_dead_bridge_turn_retries_once_with_fresh_client(monkeypatch):
    from api.providers.jaeger import streaming

    calls = []

    class Client:
        def is_alive(self):
            return True

        def close(self):
            return None

        def turn(self, text, **_kwargs):
            calls.append(text)
            if len(calls) == 1:
                raise BrokenPipeError(32, "broken pipe")
            return {"text": "recovered", "error": None}

    monkeypatch.setattr(streaming, "_jaeger_instance_name", lambda: "test")
    monkeypatch.setattr(streaming, "_get_or_start_bridge_client", lambda _instance: Client())
    monkeypatch.setattr(streaming, "_evict_bridge_client", lambda *_args: None)

    result = streaming._run_local_jaeger_turn(
        "hello", "session-1", "/tmp/workspace", threading.Event()
    )

    assert result == ("recovered", "", [])
    assert calls == ["hello", "hello"]


def test_bridge_failure_is_redacted_before_log_or_api(monkeypatch, caplog):
    from api.providers.jaeger import streaming

    secret = "ghp_TestFakeCredential1234567890ab"

    class Client:
        def close(self):
            return None

        def turn(self, *_args, **_kwargs):
            raise RuntimeError(f"provider rejected token={secret}")

    monkeypatch.setattr(streaming, "_jaeger_instance_name", lambda: "test")
    monkeypatch.setattr(streaming, "_get_or_start_bridge_client", lambda _instance: Client())
    monkeypatch.setattr(streaming, "_evict_bridge_client", lambda *_args: None)

    _text, error, _activity = streaming._run_local_jaeger_turn(
        "hello", "session-1", "/tmp/workspace", threading.Event()
    )

    assert secret not in error
    assert secret not in caplog.text


def test_bridge_tool_frames_are_redacted_before_ui_and_trace():
    from api.providers.jaeger import streaming

    secret = "ghp_TestFakeCredential1234567890ab"
    emitted = []
    streaming._translate_bridge_frame(
        {
            "type": "tool",
            "name": "remote_call",
            "phase": "start",
            "preview": f"calling with {secret}",
            "args": {"token": secret},
        },
        lambda kind, payload: emitted.append((kind, payload)),
        "",
    )
    assert secret not in repr(emitted)


def test_bridge_tool_frames_mask_opaque_values_under_secret_keys():
    from api.providers.jaeger import streaming

    emitted = []
    streaming._translate_bridge_frame(
        {
            "type": "tool",
            "name": "remote_call",
            "phase": "start",
            "args": {"api_key": "opaque-value", "nested": {"password": "plain-word"}},
        },
        lambda kind, payload: emitted.append((kind, payload)),
        "",
    )
    assert "opaque-value" not in repr(emitted)
    assert "plain-word" not in repr(emitted)


def test_same_instance_turns_are_serialized(monkeypatch):
    from api.providers.jaeger import streaming

    active = 0
    peak = 0
    state_lock = threading.Lock()

    class Client:
        def turn(self, text, **_kwargs):
            nonlocal active, peak
            with state_lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with state_lock:
                active -= 1
            return {"text": text, "error": None}

    client = Client()
    monkeypatch.setattr(streaming, "_jaeger_instance_name", lambda: "shared")
    monkeypatch.setattr(streaming, "_get_or_start_bridge_client", lambda _instance: client)
    streaming._BRIDGE_TURN_LOCKS.clear()

    results = []
    workers = [
        threading.Thread(
            target=lambda value=value: results.append(
                streaming._run_local_jaeger_turn(
                    value, f"session-{value}", "/tmp/workspace", threading.Event()
                )
            )
        )
        for value in ("one", "two")
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2)

    assert all(not worker.is_alive() for worker in workers)
    assert peak == 1
    assert {row[0] for row in results} == {"one", "two"}


def test_stale_instance_lock_is_cleared_and_retried_once(monkeypatch):
    """A dead orphan's lock recovers automatically instead of needing `jaeger kill` by hand."""
    from api.providers.jaeger import streaming

    starts = []

    class FakeClient:
        def __init__(self, *, jaeger_home, instance):
            self._attempt = len(starts) + 1
            starts.append(self._attempt)

        def start(self):
            if self._attempt == 1:
                raise streaming.JaegerError(
                    "instance 'jarvis' is locked by pid 20822 (still running)."
                )
            return {"ok": True}

        def close(self):
            return None

        def is_alive(self):
            return True

    clear_calls = []

    monkeypatch.setattr(streaming, "local_jaeger_root", lambda: __import__("pathlib").Path("/tmp"))
    monkeypatch.setattr(streaming, "JaegerClient", FakeClient)
    monkeypatch.setattr(
        streaming,
        "_force_clear_stale_instance_lock",
        lambda instance: clear_calls.append(instance) or True,
    )
    streaming._BRIDGE_CLIENTS.clear()
    streaming._BRIDGE_TURN_LOCKS.clear()

    client = streaming._get_or_start_bridge_client("jarvis")

    assert isinstance(client, FakeClient)
    assert starts == [1, 2]
    assert clear_calls == ["jarvis"]


def test_lock_error_surfaces_when_auto_recovery_cannot_clear_it(monkeypatch):
    """A genuinely-live second instance still gets a clear error, not a silent hang."""
    from api.providers.jaeger import streaming

    class AlwaysLockedClient:
        def __init__(self, *, jaeger_home, instance):
            pass

        def start(self):
            raise streaming.JaegerError(
                "instance 'jarvis' is locked by pid 999 (still running)."
            )

        def close(self):
            return None

    monkeypatch.setattr(streaming, "local_jaeger_root", lambda: __import__("pathlib").Path("/tmp"))
    monkeypatch.setattr(streaming, "JaegerClient", AlwaysLockedClient)
    monkeypatch.setattr(streaming, "_force_clear_stale_instance_lock", lambda instance: False)
    streaming._BRIDGE_CLIENTS.clear()
    streaming._BRIDGE_TURN_LOCKS.clear()

    try:
        streaming._get_or_start_bridge_client("jarvis")
        assert False, "expected JaegerError"
    except streaming.JaegerError as exc:
        assert "locked" in str(exc).lower()
