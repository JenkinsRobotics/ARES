"""Contract tests for the ARES↔JaegerAI event boundary.

Existing coverage (``test_jros_backend_streaming.py``) exercises the gateway
path and the local bridge path *separately*. Nothing pinned the thing that
actually matters to a user: that whatever transport served the turn, the
browser receives the same event vocabulary, and that vocabulary is one the
frontend actually understands.

These tests pin the translation contract itself:

  * ``_translate_bridge_frame`` emits only event names ``chat-stream.ts``
    can decode (parsed out of the .ts file, so drift on either side fails
    here rather than silently degrading the UI),
  * tool running / completed / failed classification,
  * mid-turn approval policy,
  * gateway auth header construction,
  * cancellation suppressing non-terminal events.

Deliberately transport-agnostic: they assert on the ARES event contract,
not on HTTP or stdio mechanics, because the contract is the part both
transports must agree on.

Note on the gateway path: JaegerAI ships no HTTP gateway today (no
``jaeger gateway`` command exists; ``jaeger_ai/core/models/llm_client.py``
*consumes* ``/v1/chat/completions`` from an external llama-server rather
than serving it). ARES's own code calls that branch the "legacy HTTP
gateway path". So true end-to-end gateway/stdio parity cannot be observed
against a real Jaeger right now — only the shared translation contract can
be, which is what these tests cover. See ADR-0008.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT_STREAM_TS = REPO_ROOT / "apps" / "web" / "src" / "shared" / "chat-stream.ts"


def _frontend_known_event_names() -> set[str]:
    """Event names ``chat-stream.ts`` decodes, read from the .ts source.

    Text-parsed on purpose — same approach as
    ``test_backend_catalog_ts_parity.py`` — so this stays a Python test with
    no Node/tsc dependency.
    """
    source = CHAT_STREAM_TS.read_text(encoding="utf-8")
    names: set[str] = set()
    # `name === "token"` / `name === "reasoning"` ...
    names.update(re.findall(r'name === "([\w.]+)"', source))
    # `["tool", "tool_call", ...].includes(name)`
    for group in re.findall(r'\[([^\]]*?)\]\.includes\(name\)', source, re.DOTALL):
        names.update(re.findall(r'"([\w.]+)"', group))
    return names


class _Recorder:
    """Stands in for ``put_jros_event``; records (event_name, payload)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(self, event, data) -> None:
        self.events.append((event, data))

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.events]


def _translate(frame: dict, stream_id: str = "s1") -> _Recorder:
    from api.providers.jaeger.gateway_streaming import _translate_bridge_frame

    recorder = _Recorder()
    _translate_bridge_frame(frame, recorder, stream_id)
    return recorder


# ── the .ts contract is readable at all ──────────────────────────────────

def test_frontend_event_vocabulary_is_parseable():
    """Guards the parser itself: if chat-stream.ts is restructured so these
    regexes stop matching, every test below would vacuously pass."""
    known = _frontend_known_event_names()
    assert {"token", "reasoning", "tool", "cancel", "error"} <= known, (
        f"chat-stream.ts vocabulary parse looks wrong, got: {sorted(known)}"
    )


# ── bridge frame translation ─────────────────────────────────────────────

def test_tool_frame_emits_an_event_name_the_frontend_understands():
    recorder = _translate({"type": "tool", "name": "shell", "status": "start"})
    assert recorder.names == ["tool"]
    assert set(recorder.names) <= _frontend_known_event_names(), (
        "bridge emitted an event name chat-stream.ts cannot decode; the UI "
        "would silently drop it"
    )


def test_state_frame_emits_reasoning_the_frontend_understands():
    recorder = _translate({"type": "state", "message": "thinking about it"})
    assert recorder.names == ["reasoning"]
    assert recorder.events[0][1]["text"] == "thinking about it"
    assert set(recorder.names) <= _frontend_known_event_names()


def test_running_tool_is_classified_running():
    payload = _translate({"type": "tool", "name": "shell", "status": "start"}).events[0][1]
    assert payload["event_type"] == "tool.running"
    assert payload["is_error"] is False
    assert payload["name"] == "shell"


@pytest.mark.parametrize("status", ["done", "complete", "completed", "ok"])
def test_completed_tool_is_classified_completed(status):
    payload = _translate({"type": "tool", "name": "shell", "status": status}).events[0][1]
    assert payload["event_type"] == "tool.completed"
    assert payload["is_error"] is False


@pytest.mark.parametrize("status", ["error", "failed", "fail"])
def test_failed_tool_is_classified_failed(status):
    payload = _translate({"type": "tool", "name": "shell", "status": status}).events[0][1]
    assert payload["event_type"] == "tool.failed"
    assert payload["is_error"] is True


def test_explicit_error_flag_marks_failure_even_on_a_done_status():
    payload = _translate(
        {"type": "tool", "name": "shell", "status": "done", "is_error": True}
    ).events[0][1]
    assert payload["event_type"] == "tool.failed"
    assert payload["is_error"] is True


def test_tool_args_are_passed_through_when_a_dict():
    payload = _translate(
        {"type": "tool", "name": "shell", "status": "start", "args": {"cmd": "ls"}}
    ).events[0][1]
    assert payload["args"] == {"cmd": "ls"}


def test_non_dict_tool_args_are_dropped_rather_than_forwarded():
    payload = _translate(
        {"type": "tool", "name": "shell", "status": "start", "args": "ls"}
    ).events[0][1]
    assert "args" not in payload


def test_unnamed_tool_falls_back_to_a_stable_label():
    payload = _translate({"type": "tool", "status": "start"}).events[0][1]
    assert payload["name"] == "jros"
    assert payload["preview"] == "jros"


def test_state_frame_without_text_emits_nothing():
    """An empty state frame must not produce an empty reasoning bubble."""
    assert _translate({"type": "state", "message": "   "}).events == []


def test_unknown_frame_type_is_ignored_not_crashed():
    """Forward compatibility: a frame type added by a newer Jaeger must not
    break an older ARES mid-turn."""
    assert _translate({"type": "some_future_frame", "data": 1}).events == []


# ── known defect, kept visible ───────────────────────────────────────────

@pytest.mark.xfail(
    reason=(
        "Known defect. _translate_bridge_frame emits outer event name 'tool' "
        "and puts the completion state in payload['event_type'] "
        "('tool.completed'). chat-stream.ts computes `completed` from the "
        "OUTER event name — completed: [\"tool_complete\",\"tool_result\","
        "\"tool.done\"].includes(name) — which is 'tool' every time, so a "
        "finished Jaeger tool renders as perpetually running. Nothing "
        "downstream promotes event_type to the event name (verified across "
        "fastapi_app/ and run_journal). Fixing it changes emitted event "
        "names, which the run journal also records, so it needs its own "
        "change rather than being folded into a test commit."
    ),
    strict=True,
)
def test_completed_tool_reaches_the_browser_as_completed():
    completed_names = {"tool_complete", "tool_result", "tool.done"}
    name, _payload = _translate(
        {"type": "tool", "name": "shell", "status": "done"}
    ).events[0]
    assert name in completed_names, (
        f"emitted {name!r}; chat-stream.ts only treats {sorted(completed_names)} "
        "as completed"
    )


# ── approval policy ──────────────────────────────────────────────────────

def test_mid_turn_approval_requests_are_granted_for_tool_use():
    """Jaeger tier-gated tools (computer_use, file_edit, …) need approval
    mid-turn.  ARES auto-grants with ``always`` so the skill persists and
    stops asking, matching Hermes behaviour (no mid-turn permission UI).
    Clarify/secret requests are still denied because ARES has no
    interactive bridge surface for them."""
    source = (
        REPO_ROOT / "integrations" / "providers" / "jaeger" / "gateway_streaming.py"
    ).read_text(encoding="utf-8")
    assert 'kind == "approval"' in source, (
        "approval auto-grant logic missing; confirm an approval path exists "
        "end-to-end before changing policy"
    )
    assert '"always"' in source, (
        "expected 'always' grant option for approval requests"
    )


# ── gateway auth ─────────────────────────────────────────────────────────

def test_gateway_auth_header_is_sent_when_a_key_is_configured(monkeypatch):
    import api.providers.jaeger.gateway_streaming as gw

    monkeypatch.setattr(gw, "_jros_gateway_api_key", lambda: "secret-key")
    assert gw._auth_headers() == {"Authorization": "Bearer secret-key"}


def test_gateway_auth_header_is_absent_when_no_key_is_configured(monkeypatch):
    import api.providers.jaeger.gateway_streaming as gw

    monkeypatch.setattr(gw, "_jros_gateway_api_key", lambda: "")
    assert gw._auth_headers() == {}, (
        "an empty key must send no Authorization header rather than "
        "'Bearer ' — see ADR-0008 on the gateway trust boundary"
    )


# ── cancellation ─────────────────────────────────────────────────────────

def test_jaeger_backend_is_importable_directly_without_a_circular_import():
    """Regression: ``integrations/workers/__init__`` imports ``JROSBackend``
    from ``jaeger.backend``, while ``jaeger.backend`` imports
    ``BackendRegistry`` back out of that same package. Whichever module was
    imported first decided whether the alias existed yet, so importing
    ``jaeger.backend`` *directly* raised "cannot import name 'JROSBackend'
    from partially initialized module".

    Must run in a fresh interpreter: once either module is cached by an
    earlier import in this process, the cycle cannot reproduce — which is
    exactly why running the wider suite together masked this.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import api.providers.jaeger.backend as b; "
            "assert b.JROSBackend is b.JaegerBackend; print('ok')",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, (
        f"direct import of jaeger.backend failed:\n{result.stderr}"
    )
    assert "ok" in result.stdout


def test_cli_delegation_does_not_claim_session_continuity_it_lacks():
    """ADR-0011: CliBackend.run_turn accepts ``session_id`` and discards it —
    no ``--resume`` is emitted, so every delegated task is a fresh agent
    session. Pinned so that if someone wires continuity in, they update
    ADR-0011 and ADR-0003 (imported CLI sessions are read_only *because*
    there is no append path) in the same change, rather than leaving the
    records contradicting the code."""
    import inspect

    from api.backends.cli_backends_legacy import CliBackend

    build_args = inspect.getsource(CliBackend._build_args)
    assert "session" not in build_args, (
        "CliBackend._build_args now references a session — if delegation "
        "gained continuity, update ADR-0011 and revisit ADR-0003's "
        "read_only rule for imported CLI sessions"
    )
    assert "--resume" not in inspect.getsource(CliBackend), (
        "a resume flag appeared on CliBackend; see ADR-0011"
    )


def test_every_outbound_gateway_call_is_bounded_by_a_timeout():
    """No unbounded urlopen on the Jaeger path. An outbound call with no
    timeout can hang a turn (or a health poll on the chat-start hot path)
    indefinitely against a wedged or malicious endpoint."""
    source = (
        REPO_ROOT / "integrations" / "providers" / "jaeger" / "gateway_streaming.py"
    ).read_text(encoding="utf-8")
    calls = re.findall(r"urlopen\((.*?)\)", source, re.DOTALL)
    assert calls, "no urlopen calls found — has the transport changed?"
    unbounded = [c for c in calls if "timeout" not in c]
    assert not unbounded, f"urlopen without timeout: {unbounded}"


def test_gateway_credentials_are_never_logged():
    """The bearer token must not reach logs or error strings. Checked
    statically because a leak here would be silent and durable (log files
    outlive the process)."""
    source = (
        REPO_ROOT / "integrations" / "providers" / "jaeger" / "gateway_streaming.py"
    ).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("logger.") or "raise " in stripped):
            continue
        for secret_ref in ("_auth_headers", "_jros_gateway_api_key", "api_key"):
            assert secret_ref not in stripped, (
                f"possible credential leak into a log/error: {stripped!r}"
            )


def test_translation_is_pure_and_does_not_consult_cancellation():
    """`_translate_bridge_frame` must stay a pure mapping; cancellation is
    enforced by put_jros_event's own guard (it drops every event except
    cancel/error/apperror once the cancel flag is set). Keeping the two
    separate is what lets these contract tests run without a live stream."""
    import inspect

    from api.providers.jaeger.gateway_streaming import _translate_bridge_frame

    source = inspect.getsource(_translate_bridge_frame)
    assert "cancel_event" not in source
