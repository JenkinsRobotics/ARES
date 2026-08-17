# ADR-0006: JaegerAI is reached through its contract, never imported

**Status:** Accepted
**Date:** 2026-08-12
**Extends:** [ADR-0001](./0001-subprocess-workers.md) (workers are out-of-process)

> **"Note on transport" is corrected by
> [ADR-0007](./0007-chat-streaming-is-websocket.md).** It cited ADR-0005 as
> settled precedent; ADR-0005 was inaccurate when written. It also applied a
> *browser↔ARES* streaming decision to the *ARES↔Jaeger* boundary — different
> boundaries. The decision below is unaffected.
>
> **The "baseline daemon interface" claim is corrected by
> [ADR-0008](./0008-worker-access-and-the-vestigial-gateway.md).** JaegerAI
> ships no HTTP gateway; that path is vestigial, and ARES↔Jaeger is
> stdio-bridge-only in practice. The decision below is unaffected.

## Context

Three AI agents independently proposed three conflicting architectures for how
ARES should reach JaegerAI — protocol-plus-WebSocket, in-process library import
of Jaeger's agent core, and a library/service split — and produced competing
in-flight work.

All three re-derived a question **ADR-0001 had already answered**. That ADR was
deleted during the docs reorganization, taking the reasoning with it; without
the record, "just import it, it's faster" looked like a fresh insight rather
than a reversal. This ADR exists as much to restore the boundary as to extend
it. (The directory has been restored; deleting an accepted ADR is how a
deliberate decision gets silently reversed.)

What is genuinely new since ADR-0001: JaegerAI now ships its own Swift client
(`jaeger_ai/interfaces/swift/Sources/JaegerOS/Bridge/BridgeProcess.swift`),
which spawns its own bridge process and speaks the same NDJSON frames ARES
does. Two independent clients of one agent is a case ADR-0001 did not consider.

## Decision

ARES accesses JaegerAI **exclusively through its versioned client contract**
(`JaegerClient`) and does not import its agent core. The supported local binding
is `jaeger bridge` over NDJSON stdio. HTTP gateway environment variables are
legacy compatibility inputs and must not be treated as proof that Jaeger ships
an HTTP service.

The bridge handshake must validate the wire protocol version. A subsequent
`query: contract` negotiation is authoritative for product features, supported
queries and commands, ownership, and mutation support. ARES fails closed when
that contract is missing, malformed, or incompatible. Backend names, package
versions, source-tree inspection, and UI assumptions are not capability APIs.

A protocol boundary, a daemon, and a specific transport are **three separate
decisions**. Only the first is settled here.

## Consequences

Good:

- A Python importable core cannot serve Jaeger's Swift client, so the contract
  must exist regardless. Given that, one interface for every client is the
  standard single-interface principle — the reason LSP exists instead of
  editors importing compiler internals. Privileging ARES with in-process access
  while other surfaces use the contract forks behaviour across two paths.
- Preserves everything ADR-0001 bought: fault isolation, version independence,
  framework-agnosticism.
- Transport changes stay beneath the `JaegerClient` facade; callers
  (`companion_control.py`, `JaegerBackend.run_turn`) do not change.
- Feature additions become additive contract changes rather than coordinated
  hard-coded matrices in two repositories.

Costs:

- Jaeger's warm state (loaded model, KV cache, sessions) still dies with the
  process that owns it. ADR-0001 anticipated the fix — "measure it against a
  warm-worker daemon" — but daemon lifecycle is **not decided here** (below).
- No live model hot-swap: `reset_jaeger_runtime()` records that Jaeger's client
  model is fixed at construction. Externalising inference does not by itself
  make switching hot; that is a client-construction constraint, not only a
  model-loading one.

## Adopted from the rejected proposal

Layering Jaeger's agent loop away from PySide6, from llama-cpp loading, and
from any specific transport is textbook ports-and-adapters and is endorsed as
**JaegerAI-internal** work. It is what makes multiple transport bindings and a
swappable model backend clean. Only its conclusion — that ARES should then
import that core — is rejected. Good internal layering and external protocol
access are complementary.

## Deliberately not decided here

Each needs its own ADR; none is authorised by this one.

- **Daemon ownership and lifecycle.** "Any client that finds no daemon spawns
  one" races: two clients can both observe "not running" and both spawn. Needs
  a single lifecycle authority (launchd/systemd or socket activation), or an
  atomic lock plus PID/endpoint metadata, readiness handshake, and stale-lock
  recovery.
- **Multi-client protocol semantics.** Version and capability negotiation are
  now required for the current bridge. A future shared daemon additionally
  needs client/session/turn/request IDs, correlation of
  streaming chunks with tool events and approvals, cancellation, reconnect and
  resume, ordering, backpressure, concurrent-turn policy, and session
  isolation. Today's frames are single-client; reusing them unchanged is not a
  safe multi-client protocol.
- **Security and trust boundary.** *Release-blocking.* A daemon that can be
  auto-started, reached by several clients, and invoke privileged tools needs a
  threat model ARES does not have: loopback-only default, authentication,
  per-client scopes, TLS beyond loopback, MCP tool authorisation, secret
  redaction, audit logging.
- **Local inference backend.** Compare a model-provider port with both Ollama
  and in-process llama.cpp adapters against mandating Ollama, on performance,
  model-format support, GPU placement, tool calling, embeddings, and offline
  behaviour. Mandating one service discards Jaeger's existing llama.cpp path.
- **MCP tool exposure.** Publishing all 121 Jaeger tools wholesale is unsafe;
  needs capability classification, schemas, per-tool permissions, and an
  allowlist. ARES already ships an MCP server
  (`services/controller/mcp_server.py`); Jaeger's side is still a placeholder
  (`integrations/providers/jaeger/backend.py:217`).

## Note on transport

ADR-0005 already chose SSE over WebSocket and set the bar for revisiting:
streaming becoming "genuinely bidirectional and latency-sensitive." Mid-turn
approval prompts (`request` frames) are the strongest candidate, but that case
has not been made with measurements. Do not add a WebSocket transport on the
grounds that Jaeger's protocol docs mention one. ADR-0005 also warns that
`realtime.py`'s existing WebSocket route "should not be treated as a second
parallel implementation without a product decision" — that still holds.

## Revisit if

Jaeger stops shipping non-Python clients **and** the multi-worker requirement
in ADR-0001 disappears — both, not either. Startup latency alone is not
sufficient grounds; it is an argument for a warm daemon, which this ADR leaves
open, not for dissolving the boundary.
