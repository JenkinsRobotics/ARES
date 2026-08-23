"""The chat-stream contract, enforced.

ARES kept hermes-webui's browser code and rewrote the backend under it, so the
SSE event vocabulary is an interface crossing a rewrite boundary. These tests
are what stops it drifting again:

  * the relay's terminal set is the contract's, not a local copy
  * every producer guarantees a relay-closing event on every path
  * every backend adapter meets the required floor, and its distance from
    full parity is reported rather than silently tolerated

The parity gap is asserted against a recorded baseline. Closing an event
removes it from the baseline; the test fails if a gap re-opens.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from api.stream_contract import (
    BACKEND_EXPECTED_EVENTS,
    BACKEND_REQUIRED_EVENTS,
    CHAT_STREAM_EVENTS,
    OUT_OF_BAND_EVENTS,
    TERMINAL_EVENTS,
    is_terminal,
)

_ROOT = Path(__file__).resolve().parents[3]
_CONTROLLER = _ROOT / "services" / "controller"

# Every module that produces chat-stream events, and the callable it uses to do
# it. Adding a backend means adding a row here — that is the point.
_PRODUCERS: dict[str, tuple[Path, tuple[str, ...]]] = {
    "agent": (_CONTROLLER / "api" / "streaming.py", ("put_event", "put")),
    "gateway": (_CONTROLLER / "api" / "gateway_chat.py", ("put_gateway_event",)),
    "jaeger": (
        _ROOT / "integrations" / "providers" / "jaeger" / "streaming.py",
        ("put_event", "put_jaeger_event"),
    ),
}

# Events a producer emits through a computed name rather than a literal, which
# the AST scan below cannot see. Each entry records where the name is resolved
# so the exemption stays auditable instead of becoming a blanket ignore.
_DYNAMIC_EMISSIONS: dict[str, frozenset[str]] = {
    # integrations/providers/jaeger/sse_events.py::tool_sse_event maps the
    # bridge's `phase: start|done|error` onto these two names.
    "jaeger": frozenset({"tool", "tool_complete"}),
}

# Recorded parity gap per backend: expected events the adapter does not emit
# yet. Shrink these as adapters are completed; never grow one without a note.
_KNOWN_PARITY_GAP: dict[str, frozenset[str]] = {
    "agent": frozenset(),
    "gateway": frozenset({"tool", "tool_complete", "state_saved", "metering"}),
    # At parity. The last gap, `reasoning`, closed once JaegerOS was absorbed
    # into the JaegerAI monorepo and could take a new additive frame type:
    # the adapters now hand their stripped `<think>` text to the loop instead
    # of discarding it. `metering` closed when bridge_client stopped throwing
    # away the reply frame's ctx_used/ctx_max; `state_saved` reuses the
    # ARES-side persistent-state diff the agent path already ran.
    "jaeger": frozenset(),
}


def _emitted_events(path: Path, callables: tuple[str, ...]) -> set[str]:
    """Event names a module emits via string literals, found by AST."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name not in callables:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
    return found


def _backend_events(backend: str) -> set[str]:
    path, callables = _PRODUCERS[backend]
    return _emitted_events(path, callables) | set(_DYNAMIC_EMISSIONS.get(backend, ()))


# ── the contract itself ────────────────────────────────────────────────────


def test_terminal_events_are_a_subset_of_the_declared_vocabulary():
    assert TERMINAL_EVENTS <= CHAT_STREAM_EVENTS
    assert OUT_OF_BAND_EVENTS <= CHAT_STREAM_EVENTS


def test_apperror_closes_a_stream():
    """The regression this module exists for.

    Every producer ends a failed turn on ``apperror`` alone. A relay that does
    not treat it as terminal never returns, and journal replay never sees a
    finished run.
    """
    assert is_terminal("apperror")
    assert "apperror" in TERMINAL_EVENTS


def test_relay_uses_the_shared_terminal_set_and_does_not_redeclare_it():
    source = (
        _CONTROLLER / "fastapi_app" / "routers" / "realtime.py"
    ).read_text(encoding="utf-8")
    assert "from api.stream_contract import" in source
    # A literal set assigned to the terminal name is the exact shape of the
    # original bug: a private copy that silently falls behind the contract.
    assert not re.search(r"_TERMINAL_EVENTS\s*=\s*\{", source)

    from fastapi_app.routers import realtime

    assert realtime._TERMINAL_EVENTS is TERMINAL_EVENTS


# ── producer obligations ───────────────────────────────────────────────────


@pytest.mark.parametrize("backend", sorted(_PRODUCERS))
def test_producer_guarantees_a_terminal_event_on_every_path(backend):
    """A ``finally`` must emit ``stream_end`` when nothing else closed the run.

    Without it, terminal-set membership is load-bearing: any failure path that
    forgets to emit leaves the relay waiting on a producer that has already
    torn its queue down.
    """
    path, _ = _PRODUCERS[backend]
    source = path.read_text(encoding="utf-8")
    if backend == "agent":
        pytest.skip("inherited donor path; covered by its own suite")
    assert "sent_terminal" in source, f"{path.name} has no terminal-event guarantee"
    assert re.search(
        r"if not sent_terminal:\s*\n\s*put_\w*event\(\s*[\"']stream_end[\"']",
        source,
    ), f"{path.name} does not emit stream_end from its finally"


@pytest.mark.parametrize("backend", sorted(_PRODUCERS))
def test_producer_only_emits_declared_event_names(backend):
    emitted = _backend_events(backend)
    undeclared = emitted - CHAT_STREAM_EVENTS
    assert not undeclared, (
        f"{backend} emits undeclared event(s) {sorted(undeclared)}; "
        "add them to api.stream_contract.CHAT_STREAM_EVENTS first"
    )


@pytest.mark.parametrize("backend", sorted(_PRODUCERS))
def test_backend_meets_the_required_floor(backend):
    emitted = _backend_events(backend)
    missing = BACKEND_REQUIRED_EVENTS - emitted
    assert not missing, (
        f"{backend} cannot render a turn: missing {sorted(missing)}"
    )


@pytest.mark.parametrize("backend", sorted(_PRODUCERS))
def test_backend_parity_gap_matches_the_recorded_baseline(backend):
    """Report distance from parity, and fail if a closed gap re-opens."""
    emitted = _backend_events(backend)
    gap = (BACKEND_EXPECTED_EVENTS - emitted) - OUT_OF_BAND_EVENTS
    expected_gap = _KNOWN_PARITY_GAP[backend]

    regressed = gap - expected_gap
    assert not regressed, (
        f"{backend} lost event(s) {sorted(regressed)} that it used to emit"
    )

    closed = expected_gap - gap
    assert not closed, (
        f"{backend} now emits {sorted(closed)} — remove them from "
        "_KNOWN_PARITY_GAP so the baseline stays honest"
    )
