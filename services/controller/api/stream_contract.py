"""The chat-stream event contract — one source of truth for every transport.

ARES kept hermes-webui's browser code and rewrote the backend underneath it, so
the SSE/WebSocket event vocabulary is now an interface that crosses a rewrite
boundary. It has to be written down somewhere both sides import, or it drifts:
the terminal-event set used to live in ``run_journal.py`` (hermes) and was
re-declared inside a transport router during the FastAPI rewrite, which is how
``apperror`` quietly stopped closing a stream. A protocol constant owned by a
router is a bug waiting to be re-introduced.

Producers (``api.streaming``, ``api.gateway_chat``,
``integrations.providers.jaeger.streaming``) and relays
(``fastapi_app.routers.realtime``) both import from here. Nothing else should
declare an event name as a literal in a control-flow comparison.
"""

from __future__ import annotations

# ── Terminal events ────────────────────────────────────────────────────────
# A relay MUST close the connection after forwarding one of these, and journal
# replay MUST treat a run whose last event is one of these as finished.
#
# ``apperror`` belongs here and its absence is not theoretical: every failure
# path in every producer ends the run on ``apperror`` alone — ``stream_end`` is
# emitted on success. Leaving it out means a failed turn's relay never returns,
# replay never sees a terminal event, and WebSocket clients are handed
# ``terminal: false`` for a run that is over.
TERMINAL_EVENTS: frozenset[str] = frozenset({
    "stream_end",
    "cancel",
    "apperror",
    "error",
})

# ── Out-of-band events ─────────────────────────────────────────────────────
# Delivered on their own SSE channels (``/api/approval/stream``,
# ``/api/clarify/stream``) rather than the chat stream, because they outlive a
# single run and must survive a chat reconnect. A backend is NOT required to
# put these on the chat stream; it is required to route them to the approval
# and clarify queues, which notify those channels.
OUT_OF_BAND_EVENTS: frozenset[str] = frozenset({
    "approval",
    "clarify",
})

# ── The full chat-stream vocabulary ────────────────────────────────────────
# Every event the browser has a handler for on the chat stream. ``api.streaming``
# is the reference implementation: it emits all of these, and the frontend was
# written against it. A new event name must be added here before it is emitted.
CHAT_STREAM_EVENTS: frozenset[str] = frozenset({
    # text
    "token",
    "reasoning",
    "interim_assistant",
    # tools
    "tool",
    "tool_complete",
    # context lifecycle
    "context_status",
    "compressing",
    "compressed",
    # session bookkeeping
    "state_saved",
    "title",
    "title_status",
    "metering",
    # goals
    "goal",
    "goal_continue",
    # steering
    "pending_steer_leftover",
    # advisory
    "warning",
    # completion
    "done",
    *TERMINAL_EVENTS,
    *OUT_OF_BAND_EVENTS,
})

# ── What a backend adapter owes the frontend ───────────────────────────────
# The floor every registered chat backend must meet for a normal successful
# turn. Kept deliberately small: these are the events without which the browser
# cannot render a turn at all, not the events that make it render well.
#
# ``BACKEND_EXPECTED_EVENTS`` is the parity target — the events
# ``api.streaming`` supplies that a second backend should also supply before it
# is considered at feature parity. The conformance test reports these as a gap
# rather than a failure, so a partially-implemented adapter is visible without
# being a red build.
BACKEND_REQUIRED_EVENTS: frozenset[str] = frozenset({
    "token",
    "done",
    "stream_end",
})

BACKEND_EXPECTED_EVENTS: frozenset[str] = frozenset({
    "token",
    "tool",
    "tool_complete",
    "reasoning",
    "metering",
    "state_saved",
    "context_status",
    "done",
    "stream_end",
})


def is_terminal(event: str) -> bool:
    """Whether forwarding ``event`` ends the run for relays and replay."""
    return str(event or "") in TERMINAL_EVENTS


def is_known_chat_event(event: str) -> bool:
    """Whether ``event`` is part of the declared chat-stream vocabulary.

    Relays forward unknown events rather than dropping them — an adapter ahead
    of this file is better than a silently swallowed frame — but tests use this
    to catch a name that was invented at a call site and never declared.
    """
    return str(event or "") in CHAT_STREAM_EVENTS


__all__ = [
    "TERMINAL_EVENTS",
    "OUT_OF_BAND_EVENTS",
    "CHAT_STREAM_EVENTS",
    "BACKEND_REQUIRED_EVENTS",
    "BACKEND_EXPECTED_EVENTS",
    "is_terminal",
    "is_known_chat_event",
]
