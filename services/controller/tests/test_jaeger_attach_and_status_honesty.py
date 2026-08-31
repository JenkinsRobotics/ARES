"""Contracts for two things the Jaeger turn path reports about itself.

Both are behaviours a passing turn never exercises, so they were invisible to
the rest of the suite: what ARES *says* when the bridge refuses, and where ARES
*looks* for a bridge that is already running. Both were established against the
live runtime rather than inferred; the commands and output are recorded in
``docs/verification/jaeger-turn-path-evidence.md``.

Three of these landed as ``xfail(strict=True)`` failing contracts, stating
behaviour the code claimed in its own comments and did not have. All three have
since been fixed and the markers removed; they now guard the fixes as ordinary
assertions. Keep that shape for anything new here — a finding gets a strict
xfail so the fix cannot land without deleting the marker and the finding
together.
"""

from __future__ import annotations

import socket

import pytest


# ── Where ARES looks for a bridge that is already running ─────────────────

def _instance_layout(tmp_path, *, sticky: str, live: str):
    """A JaegerAI home whose sticky default instance is ``sticky``."""
    home = tmp_path / "JaegerAI"
    (home / ".jaeger_ai").mkdir(parents=True)
    (home / ".jaeger_ai" / "active_instance").write_text(sticky + "\n", encoding="utf-8")
    run_dir = home / ".jaeger_ai" / "instances" / live / "run"
    run_dir.mkdir(parents=True)
    return home, run_dir / "bridge.sock"


def test_attach_candidates_include_the_home_instance_dir(tmp_path):
    """The explicit-selector case works, and is what the suite covered before."""
    from api.providers.jaeger.paths import jaeger_bridge_socket_candidates

    home, sock = _instance_layout(tmp_path, sticky="ares", live="ares")

    assert sock in jaeger_bridge_socket_candidates(str(home), "ares")


def test_attach_candidates_follow_the_sticky_default_instance(tmp_path):
    """With no explicit selector, ARES must look where Jaeger actually serves.

    ``jaeger_instance_name()`` documents itself as returning "only an explicit
    selector; Jaeger owns default resolution", and JaegerAI resolves an unset
    instance through ``JAEGER_INSTANCE_NAME`` → the ``active_instance`` sticky
    file → the literal ``"default"``. The candidate list skips the middle step,
    which is the only one that differs on an operator machine where somebody
    has run ``jaeger agent use <name>``.
    """
    from api.providers.jaeger.paths import jaeger_bridge_socket_candidates

    home, sock = _instance_layout(tmp_path, sticky="ares", live="ares")

    assert sock in jaeger_bridge_socket_candidates(str(home), None)


def test_attach_candidates_include_current_user_state_layout(tmp_path, monkeypatch):
    """A product checkout and Jaeger's user-owned state are separate roots."""
    from api.providers.jaeger.paths import jaeger_bridge_socket_candidates

    product = tmp_path / "product" / "JaegerAI"
    product.mkdir(parents=True)
    user_home = tmp_path / "user"
    (user_home / ".jaeger_ai").mkdir(parents=True)
    (user_home / ".jaeger_ai" / "active_instance").write_text("jaeger\n", encoding="utf-8")
    socket_path = user_home / ".jaeger_ai" / "instances" / "jaeger" / "run" / "bridge.sock"
    monkeypatch.setenv("HOME", str(user_home))

    assert socket_path in jaeger_bridge_socket_candidates(str(product), None)


def test_a_stale_socket_file_is_not_mistaken_for_a_live_bridge(tmp_path):
    """A leftover socket path must fail connect rather than read as attached.

    Three such files exist on the reference machine; only one has a listener.
    ``_try_attach`` relies on connect failing for the other two.
    """
    _home, sock = _instance_layout(tmp_path, sticky="ares", live="ares")
    sock.write_bytes(b"")  # a plain file where a socket used to be

    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(2.0)
    try:
        with pytest.raises(OSError):
            probe.connect(str(sock))
    finally:
        probe.close()


# ── What ARES says when the bridge will not answer ────────────────────────

class _BridgeRefused(RuntimeError):
    """Stands in for the JaegerError a locked instance raises."""


@pytest.fixture()
def _installed_jaeger(tmp_path, monkeypatch):
    """A JaegerAI install that passes every filesystem check in status.py."""
    import os

    root = tmp_path / "JaegerAI"
    (root / "jaeger_ai").mkdir(parents=True)
    launcher = root / "jaeger"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    assert os.access(launcher, os.X_OK)

    from api.providers.jaeger import status as status_mod

    monkeypatch.setattr(status_mod, "_cached", None, raising=False)
    monkeypatch.setattr(status_mod, "_cached_at", 0.0, raising=False)
    monkeypatch.setattr(
        "api.providers.jaeger.streaming.local_jaeger_root", lambda: root
    )
    return root


def _status_with_bridge_raising(monkeypatch, exc: Exception):
    from api.providers.jaeger.status import check_status

    def _raise(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(
        "api.providers.jaeger.streaming.query_local_companion", _raise
    )
    return check_status(use_cache=False)


def test_status_is_not_connected_when_the_bridge_refuses(_installed_jaeger, monkeypatch):
    """Whatever it says, a refusing bridge must not read as ready."""
    result = _status_with_bridge_raising(
        monkeypatch, _BridgeRefused("a bridge is already running (pid 4242)")
    )

    assert result.state.value != "connected"


def test_status_names_the_bridge_failure_instead_of_blaming_the_model(
    _installed_jaeger, monkeypatch
):
    """A bridge that raises must be reported as a bridge fault, with its cause.

    status.py states the intent directly: "The bridge query is therefore the
    probe, and its failure is the status — not a swallowed detail that degrades
    the message to a shorter sentence." The swallow happens one layer down in
    ``active_model``, so the message the operator reads sends them to the model
    picker for a problem no model change can fix.
    """
    result = _status_with_bridge_raising(
        monkeypatch, _BridgeRefused("a bridge is already running (pid 4242)")
    )

    reason = str(result.details.get("reason") or "")
    assert "no serving model" not in result.message
    assert "already running" in reason, (
        f"the cause was dropped; operator sees reason={reason!r}"
    )


# ── What ARES reports about a runtime whose tools it cannot read ──────────

def _backend_with_bridge_raising(monkeypatch, exc: Exception):
    from api.providers.jaeger.backend import JaegerBackend

    def _raise(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(
        "api.providers.jaeger.streaming.query_local_companion", _raise
    )
    return JaegerBackend()


def test_tools_are_empty_when_the_bridge_cannot_be_read(monkeypatch):
    """Pins the observed behaviour: a refused bridge reports zero tools.

    Recorded, not endorsed — see the test below for the contract this
    contradicts. On the reference machine every ``list_tools`` query raised, so
    this is the branch production actually took.
    """
    backend = _backend_with_bridge_raising(
        monkeypatch, _BridgeRefused("a bridge is already running (pid 4242)")
    )

    assert backend.tools() == []


def test_an_unreadable_tool_list_is_distinguishable_from_an_empty_one(monkeypatch):
    """A runtime ARES cannot interrogate must not be reported as tool-less.

    A model told it has no tools will not call one, so this failure is not
    confined to a status panel: it silently changes what the assistant does.
    Any distinguishable signal satisfies this — an exception, a sentinel, or a
    status field callers can read — the empty list alone does not.
    """
    backend = _backend_with_bridge_raising(
        monkeypatch, _BridgeRefused("a bridge is already running (pid 4242)")
    )

    tools = backend.tools()
    unknown = backend.inventory().get("active_execution", {}).get("tools_unknown")

    assert tools != [] or unknown is True, (
        "a refused bridge is reported as a runtime with zero tools"
    )


def test_no_serving_model_is_distinct_from_a_refusing_bridge(_installed_jaeger, monkeypatch):
    """Promise 12: no configured model must not share the bridge-down message."""
    from api.providers.jaeger.status import check_status

    monkeypatch.setattr(
        "api.providers.jaeger.streaming.query_local_companion",
        lambda *_args, **_kwargs: {"serving": {}, "configured": {}},
    )
    no_model = check_status(use_cache=False)
    refused = _status_with_bridge_raising(
        monkeypatch, _BridgeRefused("a bridge is already running (pid 4242)")
    )

    assert "no serving model" in no_model.message
    assert "bridge is not answering" not in no_model.message
    assert "no serving model" not in refused.message
    assert "bridge is not answering" in refused.message


def test_a_locked_bridge_reason_names_the_lock(_installed_jaeger, monkeypatch):
    """Promise 12: a live instance lock must be distinguishable from a dead probe."""
    locked = _status_with_bridge_raising(
        monkeypatch, _BridgeRefused("a bridge is already running for this instance (pid 4242)")
    )
    dead = _status_with_bridge_raising(
        monkeypatch, ConnectionRefusedError("Connection refused")
    )

    assert locked.state.value == "needs_attention"
    assert dead.state.value == "needs_attention"
    locked_reason = str(locked.details.get("reason") or "")
    dead_reason = str(dead.details.get("reason") or "")
    assert "already running" in locked_reason
    assert "already running" not in dead_reason
    # The details.reason field distinguishes them. The operator-visible
    # message currently does not; record that so a UI that only renders
    # message cannot claim this promise.
    assert locked_reason != dead_reason


def test_genuine_empty_tools_are_not_marked_unknown(monkeypatch):
    """Promise 12: an authoritative empty inventory is not an unknown inventory."""
    from api.providers.jaeger.backend import JaegerBackend

    monkeypatch.setattr(
        "api.providers.jaeger.streaming.query_local_companion",
        lambda *_args, **_kwargs: [],
    )
    backend = JaegerBackend()
    tools, unknown = backend._tools_inventory()
    assert tools == []
    assert unknown is False
    assert backend.tools() == []


def test_legacy_adapters_payload_collapses_unknown_tools_to_empty(monkeypatch):
    """`/api/ares/adapters` still uses tools(), which cannot carry tools_unknown."""
    backend = _backend_with_bridge_raising(
        monkeypatch, _BridgeRefused("a bridge is already running (pid 4242)")
    )
    payload = {
        "tools": backend.tools(),
        "inventory_unknown": backend.inventory().get("active_execution", {}).get("tools_unknown"),
    }
    assert payload["tools"] == []
    assert payload["inventory_unknown"] is True
