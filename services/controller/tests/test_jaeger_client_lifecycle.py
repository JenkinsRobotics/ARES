"""Lifecycle contracts for the ARES Jaeger bridge client.

These pin recovery/shutdown behaviour that a passing model turn never
exercises: process-kill policy, reader-thread close, and non-replay of a
turn whose tool side effect already committed.
"""
from __future__ import annotations

import inspect
import json
import socket
import threading
import time
from pathlib import Path

from api.providers.jaeger.backend import JaegerBackend
from api.providers.jaeger.bridge_client import JaegerClient
from api.providers.jaeger.streaming import run_jaeger_streaming


STREAMING_PATH = (
    Path(__file__).resolve().parents[3] / "integrations" / "providers" / "jaeger" / "streaming.py"
)


def test_production_streaming_never_invokes_jaeger_kill():
    source = STREAMING_PATH.read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "_force_clear_stale_instance_lock" not in source
    assert "jaeger\", \"kill\"" not in source
    assert "[str(launcher), \"kill\"" not in source


def test_dead_transport_does_not_replay_after_a_committed_side_effect(monkeypatch):
    from api.providers.jaeger import streaming

    ledger: list[str] = []
    token = "side-effect-token-1"

    class Client:
        def query(self, *_args, **_kwargs):
            return []

        def turn(self, text, **_kwargs):
            ledger.append(token)
            raise BrokenPipeError(32, "broken pipe")

    monkeypatch.setattr(streaming, "_jaeger_instance_name", lambda: "test")
    monkeypatch.setattr(streaming, "_get_or_start_bridge_client", lambda _instance: Client())
    streaming._HYDRATED_SESSIONS.clear()
    streaming._BRIDGE_CLIENTS.clear()

    text, error, _activity = streaming._run_local_jaeger_turn(
        "commit then die", "session-side-effect", "/tmp/ws", threading.Event()
    )

    assert text == ""
    assert "broken pipe" in error
    assert ledger == [token]


def test_run_local_jaeger_turn_has_a_single_attempt():
    from api.providers.jaeger import streaming

    source = inspect.getsource(streaming._run_local_jaeger_turn)
    assert "for attempt in (1,):" in source
    assert "for attempt in (1, 2)" not in source


def test_production_backend_worker_is_the_streaming_adapter():
    worker, is_gateway, is_jaeger = JaegerBackend().get_worker_target()
    assert worker is run_jaeger_streaming
    assert is_gateway is True
    assert is_jaeger is True


def test_closing_an_attached_client_does_not_raise_in_the_reader_thread():
    """Closing the attach socket must not dump an unhandled reader exception."""
    server, client_sock = socket.socketpair()
    ready = {
        "type": "ready",
        "proto": "v1",
        "capabilities": ["turn", "query"],
        "instance": "test",
        "model": "none",
    }
    server.sendall((json.dumps(ready) + "\n").encode("utf-8"))

    caught: list[BaseException] = []
    previous_hook = threading.excepthook

    def _hook(args):
        if args.exc_type is not None and args.exc_value is not None:
            caught.append(args.exc_value)
        previous_hook(args)

    threading.excepthook = _hook
    client = JaegerClient.__new__(JaegerClient)
    client._jaeger_home = None
    client._instance = "test"
    client._command = ["jaeger", "bridge"]
    client._env = {}
    client._cwd = None
    client._proc = None
    client._sock = client_sock
    client._rx = client_sock.makefile("rw", buffering=1, encoding="utf-8", newline="\n")
    client._attached = True
    client._stderr_lines = []
    client._stderr_thread = None
    client.ready = None
    client._io_lock = threading.RLock()
    client._write_lock = threading.Lock()
    client._turn_lock = threading.Lock()
    client._route_lock = threading.Lock()
    client._active_turn = None
    client._pending_requests = {}
    client._reader_thread = None
    client._request_counter = 0
    closed = threading.Event()

    def _close() -> None:
        try:
            client.close()
        finally:
            closed.set()

    try:
        client._start_reader()
        time.sleep(0.05)
        closer = threading.Thread(target=_close, name="close-attached", daemon=True)
        closer.start()
        finished = closed.wait(2.0)
        if not finished:
            try:
                server.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            closer.join(timeout=1.0)
        if client._reader_thread is not None:
            client._reader_thread.join(timeout=1.0)
        time.sleep(0.05)
        assert finished, "JaegerClient.close() hung while the attach reader was blocked"
        assert caught == [], f"reader thread raised {caught!r}"
    finally:
        threading.excepthook = previous_hook
        for sock in (server, client_sock):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
