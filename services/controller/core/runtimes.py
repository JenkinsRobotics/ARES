"""Canonical agent-runtime registry — the single source of truth for ARES.

Before this module, "which runtimes exist" was answered independently in nine
places: two duplicate ``Literal["hermes", "jaeger"]`` type definitions, a
hardcoded adapter dict, an A2A ``@prefix`` tuple, and three MCP allowlists.
Adding a runtime meant finding all of them, and the two literals had already
drifted apart in intent (one models automation agents, one models control-plane
definitions) while claiming the same closed set.

A runtime here is an *independently owned agent product* that ARES routes work
to. It is deliberately not the same concept as a chat-turn connection in
``api.backend_catalog``: a connection answers "who renders this turn", a runtime
answers "who can hold a durable goal, a run lease, and an approval". Runtimes
that also expose a turn-level connection declare it via ``backend_id`` so the
two taxonomies stop drifting (``jaeger`` / ``jaeger_local`` was the first
casualty of them not being linked).

ARES never imports a runtime's code -- everything here is identity,
deployment shape, and how to reach it from outside.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: Where the runtime's process actually lives. This drives install/verify paths
#: and the isolation story, not just a label: ``host`` runtimes are reached by
#: an on-PATH command, ``container`` runtimes only ever by their mapped
#: loopback port, and ``cloud`` runtimes by an authenticated remote endpoint.
Deployment = Literal["host", "container", "cloud"]

#: How ARES talks to it. ``cli`` spawns the command, ``http`` calls the
#: endpoint, ``cli+http`` means the runtime offers both and the adapter picks.
Transport = Literal["cli", "http", "cli+http"]


@dataclass(frozen=True)
class RuntimeDefinition:
    """One independently owned agent runtime ARES can route work to."""

    id: str
    label: str
    deployment: Deployment
    transport: Transport
    #: On-PATH command name, for ``cli``/``cli+http`` runtimes. Empty for pure
    #: HTTP runtimes. Presence on PATH is a *probe* concern, not a registry
    #: one -- the registry says what to look for, the adapter says if it's there.
    command: str = ""
    #: Loopback URL for ``http``/``cli+http`` runtimes. Container runtimes must
    #: always carry one, since the command is not reachable from the host.
    endpoint: str = ""
    #: True when the runtime can hold ARES goals, run leases, and approvals.
    #: False means it is registered and classifiable but not yet promoted --
    #: it needs an adapter implementing probe/start_run/cancel_run first.
    durable: bool = False
    #: Matching ``api.backend_catalog`` connection id, when the same product is
    #: also selectable as a chat-turn backend. Empty when it is runtime-only.
    backend_id: str = ""
    #: Read-only migration boundary for ids persisted before this registry.
    aliases: tuple[str, ...] = ()


#: ARES-internal identity that is not a runtime but is accepted where an actor
#: id is expected (capability grants, host-capability MCP).
ADMIN_IDENTITY = "admin"


RUNTIMES: tuple[RuntimeDefinition, ...] = (
    RuntimeDefinition(
        id="hermes",
        label="Hermes Agent",
        deployment="container",
        transport="cli+http",
        command="hermes",
        endpoint="http://127.0.0.1:8787",
        durable=True,
        aliases=("hermes_agent", "hermes-agent"),
    ),
    RuntimeDefinition(
        id="jaeger",
        label="Jaeger AI",
        deployment="host",
        transport="cli+http",
        command="jaeger",
        endpoint="http://127.0.0.1:8790",
        durable=True,
        backend_id="jaeger_local",
        aliases=("jaegerai", "jaeger_ai", "jaeger_local"),
    ),
    RuntimeDefinition(
        id="openclaw",
        label="OpenClaw",
        deployment="container",
        transport="cli+http",
        command="openclaw",
        # OpenClaw's gateway default; mapped to loopback from the container.
        endpoint="http://127.0.0.1:18789",
        durable=True,
        # Deliberately empty: OpenClaw has no chat-turn connection in
        # ``api.backend_catalog`` yet. That needs its own CLI backend class
        # (model discovery, turn rendering) and is independent of running it as
        # a durable runtime. Claiming a backend id here that does not exist is
        # exactly the jaeger/jaeger_local drift this registry removes.
        backend_id="",
        # OpenClaw normalizes its own legacy `pi` harness id to `openclaw`; we
        # deliberately do NOT alias `pi` here, because `pi` is a separate
        # installed product on this host with its own runtime entry below.
        aliases=(),
    ),
    RuntimeDefinition(
        id="claude",
        label="Claude Code",
        deployment="host",
        transport="cli",
        command="claude",
        durable=False,
        backend_id="claude_local",
    ),
    RuntimeDefinition(
        id="codex",
        label="OpenAI Codex",
        deployment="host",
        transport="cli",
        command="codex",
        durable=False,
        backend_id="codex_local",
    ),
    RuntimeDefinition(
        id="gemini",
        label="Google Gemini",
        deployment="host",
        transport="cli",
        command="gemini",
        durable=False,
        backend_id="gemini_local",
    ),
    RuntimeDefinition(
        id="grok",
        label="xAI Grok",
        deployment="host",
        transport="cli",
        command="grok",
        durable=False,
        backend_id="grok_local",
    ),
    RuntimeDefinition(
        id="pi",
        label="Pi Coding Agent",
        deployment="host",
        transport="cli",
        command="pi",
        durable=False,
        backend_id="pi_local",
    ),
)

RUNTIME_BY_ID = {runtime.id: runtime for runtime in RUNTIMES}
VALID_RUNTIME_IDS = tuple(RUNTIME_BY_ID)

_ALIASES = {
    alias: runtime.id for runtime in RUNTIMES for alias in runtime.aliases
}


def normalize_runtime_id(value: object, *, fallback: str = "") -> str:
    """Resolve a persisted or user-supplied id to a canonical runtime id.

    Returns ``""`` when the value names no known runtime, so callers can tell
    "unknown" apart from "defaulted" instead of silently routing elsewhere.
    """

    raw = str(value or "").strip().lower()
    normalized = _ALIASES.get(raw, raw)
    if normalized in RUNTIME_BY_ID:
        return normalized
    raw_fallback = str(fallback or "").strip().lower()
    normalized_fallback = _ALIASES.get(raw_fallback, raw_fallback)
    return normalized_fallback if normalized_fallback in RUNTIME_BY_ID else ""


def is_runtime(value: object) -> bool:
    return bool(normalize_runtime_id(value))


def durable_runtime_ids() -> tuple[str, ...]:
    """Runtimes that may currently hold goals, runs, leases, and approvals."""

    return tuple(runtime.id for runtime in RUNTIMES if runtime.durable)


def is_durable_runtime(value: object) -> bool:
    normalized = normalize_runtime_id(value)
    return bool(normalized) and RUNTIME_BY_ID[normalized].durable


def runtime_display_name(value: object) -> str:
    normalized = normalize_runtime_id(value)
    if not normalized:
        return str(value or "")
    return RUNTIME_BY_ID[normalized].label


def is_actor_identity(value: object) -> bool:
    """True for a runtime id or the ARES ``admin`` identity.

    Capability grants and the host-capability MCP server accept both, since
    ARES itself acts on the user's behalf alongside the runtimes it routes to.
    """

    raw = str(value or "").strip().lower()
    return raw == ADMIN_IDENTITY or is_runtime(raw)
