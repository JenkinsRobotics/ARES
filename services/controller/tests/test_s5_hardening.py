"""S5 hardening: failures must be readable, recoverable, and self-explaining.

A failure the user cannot act on is a dead end. These tests pin the two ways
ARES avoids that: every blocking error carries a stated cause and a next action,
and a conversation abandoned by a dead worker can be reclaimed by sending again
instead of staying wedged behind a stream id nothing owns.
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from api import chat_runtime
from api.providers.status_contract import (
    ProviderStatus,
    ProviderStatusState,
    connected,
    needs_attention,
    not_configured,
    not_installed,
    offline,
    remediation,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── error message schema ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status",
    [
        not_installed("Runtime X is not installed."),
        not_configured("Runtime X needs an API key."),
        offline("Runtime X is not responding."),
        needs_attention("Runtime X is half configured."),
    ],
)
def test_every_blocking_status_states_a_cause_and_a_next_action(status):
    result = remediation(status)
    assert result["reason"], f"{status.state} has no reason"
    assert result["fix"], f"{status.state} has no fix"


def test_provider_supplied_remediation_wins_over_the_generic_default():
    status = not_installed(
        "JaegerAI is not installed.",
        reason="No checkout found in ~/GitHub/JaegerAI.",
        fix="Set ARES_JAEGER_HOME=/path/to/JaegerAI",
        env_hint="Discovery order: ~/jaeger, ~/GitHub/JaegerAI, ~/JaegerAI.",
    )
    result = remediation(status)
    assert result["reason"] == "No checkout found in ~/GitHub/JaegerAI."
    assert result["fix"] == "Set ARES_JAEGER_HOME=/path/to/JaegerAI"
    assert "Discovery order" in result["env_hint"]


def test_remediation_never_emits_empty_keys():
    """A blank `fix` is worse than none — it renders as an empty UI row."""
    result = remediation(ProviderStatus(ProviderStatusState.NOT_INSTALLED, ""))
    assert all(value.strip() for value in result.values())


def test_connected_status_needs_no_fix():
    assert "fix" not in remediation(connected("All good."))


def test_stale_jaeger_override_names_the_variable_and_the_repair(monkeypatch):
    """The exact misconfiguration that made Jaeger look uninstalled."""
    from api.providers.jaeger import paths, status

    for name in (paths.JAEGER_HOME_ENV, paths.ARES_JAEGER_SOURCE_DIR_ENV, paths.LEGACY_JaegerAI_DIR_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(paths.ARES_JAEGER_HOME_ENV, "/nonexistent/JaegerAI")

    result = remediation(status.check_status(use_cache=False))

    assert "ARES_JAEGER_HOME" in result["reason"]
    assert "/nonexistent/JaegerAI" in result["reason"]
    assert "ARES_JAEGER_HOME" in result["fix"]


def test_adapter_health_remediation_reaches_the_http_error_body():
    """CoreApiError spreads adapter context, so reason/fix land at top level."""
    from fastapi_app.adapters.base import AdapterHealth
    from fastapi_app.adapters.frameworks import _health_remediation
    from fastapi_app.errors import CoreApiError

    health = AdapterHealth("not_configured", False, "Runtime X needs an API key.", {})
    context = {"connection_id": "x_cloud", **_health_remediation(health)}
    payload = CoreApiError(503, health.message, code="runtime_unavailable", context=context).payload()

    assert payload["error"] == "Runtime X needs an API key."
    assert payload["reason"]
    assert payload["fix"]


def test_worker_boot_error_event_carries_a_fix(monkeypatch):
    class _Channel:
        def __init__(self):
            self.items = []

        def put_nowait(self, item):
            self.items.append(item)

    channel = _Channel()
    monkeypatch.setitem(chat_runtime.STREAMS, "s-boot", channel)
    monkeypatch.setattr(chat_runtime, "get_session", lambda *_a, **_k: (_ for _ in ()).throw(KeyError()))

    chat_runtime._publish_worker_boot_error("s-boot", "sess", TypeError("bad kwarg"))

    name, payload = channel.items[0][0], channel.items[0][1]
    assert name == "error"
    assert payload["reason"].startswith("TypeError")
    assert payload["fix"]


# ── double-send / stale stream recovery ──────────────────────────────────────


def test_busy_session_response_tells_the_user_to_retry():
    payload = chat_runtime._busy_session_response("stream-9")
    assert payload["_status"] == 409
    assert payload["retry"] is True
    assert payload["active_stream_id"] == "stream-9"
    assert payload["reason"]
    assert payload["fix"]


def test_a_live_worker_thread_is_not_treated_as_dead():
    stop = threading.Event()
    thread = threading.Thread(target=stop.wait, daemon=True)
    thread.start()
    try:
        chat_runtime._register_worker_thread("s-live", thread)
        assert chat_runtime._worker_thread_is_dead("s-live") is False
    finally:
        stop.set()
        thread.join(2)
        chat_runtime._forget_worker_thread("s-live")


def test_an_exited_worker_thread_is_reported_dead():
    thread = threading.Thread(target=lambda: None, daemon=True)
    thread.start()
    thread.join(2)
    chat_runtime._register_worker_thread("s-dead", thread)
    try:
        assert chat_runtime._worker_thread_is_dead("s-dead") is True
    finally:
        chat_runtime._forget_worker_thread("s-dead")


def test_an_unknown_stream_is_not_assumed_dead():
    """After a restart ARES owns no thread record; that is unknown, not dead."""
    assert chat_runtime._worker_thread_is_dead("never-seen") is False


def test_confirmed_thread_death_overrides_the_stale_pending_grace(monkeypatch):
    """The regression: a worker that died instantly wedged the session.

    ``_clear_stale_pending_locked`` normally waits out a grace window before
    reclaiming, to avoid racing a worker that has not registered yet. A thread
    we watched exit is not that case.
    """
    session = SimpleNamespace(
        session_id="sess-1",
        active_stream_id="s-1",
        pending_user_message="hello",
        pending_started_at=time.time(),  # well inside the grace window
        pending_attachments=[],
        pending_started_at_iso=None,
        pending_user_source="webui",
        messages=[],
        save=lambda **_k: None,
    )
    monkeypatch.setattr(chat_runtime, "_stream_is_active", lambda _sid: False)
    monkeypatch.setattr(
        "api.streaming._materialize_pending_user_turn_before_error", lambda _s: None
    )

    dead = threading.Thread(target=lambda: None, daemon=True)
    dead.start()
    dead.join(2)

    chat_runtime._forget_worker_thread("s-1")
    assert chat_runtime._clear_stale_pending_locked(session, "s-1") is False  # unknown → wait

    chat_runtime._register_worker_thread("s-1", dead)
    try:
        assert chat_runtime._clear_stale_pending_locked(session, "s-1") is True  # dead → reclaim
    finally:
        chat_runtime._forget_worker_thread("s-1")


def test_recovered_send_reports_which_stream_it_cleared(monkeypatch):
    """A retry after a dead worker must be distinguishable from a clean send."""
    from tests.test_chat_runtime import _isolate_runtime, _session

    session = _session()
    _isolate_runtime(monkeypatch, session)

    dead = threading.Thread(target=lambda: None, daemon=True)
    dead.start()
    dead.join(2)
    session.active_stream_id = "abandoned-1"
    session.pending_user_message = "earlier message"
    session.pending_started_at = time.time()
    chat_runtime._register_worker_thread("abandoned-1", dead)
    monkeypatch.setattr(
        "api.streaming._materialize_pending_user_turn_before_error", lambda _s: None
    )

    class ImmediateThread:
        def __init__(self, *, target, args, kwargs, **_rest):
            self._call = (target, args, kwargs)

        def start(self):
            pass  # the recovery decision is what matters, not the turn itself

    monkeypatch.setattr(chat_runtime.threading, "Thread", ImmediateThread)

    backend = SimpleNamespace(
        name="jaeger_local", get_worker_target=lambda: (lambda *a, **k: None, False, False)
    )
    result = chat_runtime.start_session_turn(
        session.session_id, "retry please", source="webui", backend=backend
    )

    assert result.get("_status") is None, result
    assert result["cleared_stream_id"] == "abandoned-1"
    assert result["recovered_stale_stream"] is True


# ── smoke script ─────────────────────────────────────────────────────────────


def test_smoke_script_is_executable_and_valid_bash():
    script = REPO_ROOT / "scripts" / "smoke_test.sh"
    assert script.exists(), "scripts/smoke_test.sh is missing"
    assert script.stat().st_mode & 0o111, "smoke_test.sh is not executable"
    subprocess.run(["bash", "-n", str(script)], check=True, timeout=30)


def test_smoke_script_fails_fast_when_no_controller_is_running():
    """It must report a clear failure, not hang, against a dead port."""
    script = REPO_ROOT / "scripts" / "smoke_test.sh"
    result = subprocess.run(
        ["bash", str(script), "http://127.0.0.1:1"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode != 0
    assert "not reachable" in result.stdout


def test_restart_recipe_is_documented():
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Restart / recovery" in agents
    assert "start_ares.sh" in agents
    assert "lsof" in agents
    assert "smoke_test.sh" in agents
