"""ARES-to-Jaeger live turn control contract."""

from __future__ import annotations

import io
import threading
import time
from types import SimpleNamespace


def test_bridge_client_writes_cancel_and_steer_without_waiting_for_reply():
    from api.providers.jaeger.bridge_client import JaegerClient

    stdin = io.StringIO()
    client = JaegerClient(command=["jaeger", "bridge"])
    client._proc = SimpleNamespace(stdin=stdin)

    client.cancel("webui:session-1")
    client.steer("use metric units", "webui:session-1")

    assert stdin.getvalue().splitlines() == [
        '{"op": "cancel"}',
        '{"op": "steer", "text": "use metric units"}',
    ]


def test_send_frame_carries_the_ares_session_workspace():
    from api.providers.jaeger.bridge_client import send_op

    assert send_op("write a report", "s1", "/tmp/project") == {
        "op": "send",
        "text": "write a report",
        "session": "s1",
        "workspace": "/tmp/project",
    }
    assert send_op(
        "[directives] write a report", "s1", "/tmp/project", "write a report"
    )["display_text"] == "write a report"


def test_bridge_client_validates_integration_contract(monkeypatch):
    from api.providers.jaeger.bridge_client import JaegerClient, JaegerError

    client = JaegerClient(command=["jaeger", "bridge"])
    monkeypatch.setattr(client, "query", lambda _what: {
        "contract": "ares-jaeger",
        "contract_version": 6,
        "protocol_version": "1",
        "features": {"chat": {"available": True}},
    })
    assert client.integration_contract()["features"]["chat"]["available"] is True

    monkeypatch.setattr(client, "query", lambda _what: {
        "contract": "ares-jaeger",
        "contract_version": 1,
        "protocol_version": "1",
        "features": {},
    })
    try:
        client.integration_contract()
    except JaegerError as exc:
        assert "incompatible ARES-Jaeger contract" in str(exc)
    else:
        raise AssertionError("an incompatible integration contract must fail closed")


def test_turn_control_delegates_to_the_live_bridge_client():
    from api.providers.jaeger.streaming import _JaegerBridgeTurnControl

    class FakeClient:
        def __init__(self):
            self.calls = []

        def is_alive(self):
            return True

        def cancel(self, session):
            self.calls.append(("cancel", session))

        def steer(self, text, session):
            self.calls.append(("steer", text, session))

    client = FakeClient()
    control = _JaegerBridgeTurnControl(client, "session-1")

    control.interrupt("Cancelled by user")
    assert control.steer("use metric units") is True
    assert client.calls == [
        ("cancel", "session-1"),
        ("steer", "use metric units", "session-1"),
    ]


def test_chat_steer_uses_registered_jaeger_turn_control(monkeypatch):
    from api import config
    from api.chat_control import steer_session

    class Control:
        def __init__(self):
            self.texts = []

        def steer(self, text):
            self.texts.append(text)
            return True

    control = Control()
    session = SimpleNamespace(active_stream_id="stream-1")
    monkeypatch.setattr("api.models.get_session", lambda _sid: session)
    with config.SESSION_AGENT_CACHE_LOCK:
        config.SESSION_AGENT_CACHE.pop("session-1", None)
    with config.STREAMS_LOCK:
        config.AGENT_INSTANCES["stream-1"] = control
    try:
        result = steer_session({"session_id": "session-1", "text": "focus on tests"})
    finally:
        with config.STREAMS_LOCK:
            config.AGENT_INSTANCES.pop("stream-1", None)

    assert result == {"accepted": True, "fallback": None, "stream_id": "stream-1"}
    assert control.texts == ["focus on tests"]


def test_external_jaeger_approval_blocks_until_existing_ui_response():
    from api import route_approvals

    session_id = "jaeger-approval-session"
    approval_id = "perm-1"
    answer = []

    worker = threading.Thread(
        target=lambda: answer.append(route_approvals.wait_for_external_approval(
            session_id,
            {
                "approval_id": approval_id,
                "tool": "host",
                "description": "Allow host.open_on_host?",
                "pattern_key": "host",
                "pattern_keys": ["host"],
            },
            timeout_seconds=2,
        )),
    )
    worker.start()
    deadline = time.monotonic() + 1
    while route_approvals.pending_snapshot(session_id)["pending"] is None:
        assert time.monotonic() < deadline
        time.sleep(0.01)

    payload, status = route_approvals.respond_approval(
        session_id, approval_id, "once")
    worker.join(timeout=1)

    assert status == 200
    assert payload["ok"] is True
    assert answer == ["once"]
    assert route_approvals.pending_snapshot(session_id)["pending"] is None
