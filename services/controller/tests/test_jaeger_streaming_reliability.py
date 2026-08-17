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
