# ADR-0008: Workers are reached via adapters; Jaeger's HTTP gateway is vestigial

**Status:** Accepted
**Date:** 2026-08-12
**Supersedes:** [ADR-0001](./0001-subprocess-workers.md)
**Corrects:** [ADR-0006](./0006-jaeger-access-boundary.md), the claim that the
HTTP/SSE gateway is "the baseline daemon interface"

## Context

Two problems with the recorded worker-access story, both found by checking
the records against the tree.

**1. ADR-0001 is too specific.** "Workers run as subprocesses" was accurate
when written, but ARES now reaches workers three different ways: a stdio
bridge subprocess (Jaeger), vendor SDKs over HTTPS (`ClaudeCloudBackend`,
`OpenAICloudBackend`, `XAICloudBackend`), and local HTTP (Ollama). Read
literally, ADR-0001 makes the SDK backends look like violations. They are
not — they honour the actual principle, which was never really "subprocess."

**2. ADR-0006 overstated the gateway.** It called the HTTP/SSE gateway "the
baseline daemon interface," implying a live Jaeger-side server. There isn't
one:

- No `jaeger gateway` command exists (`COMMANDS.md`, `jaeger --help`).
- `jaeger_ai/core/models/llm_client.py` **consumes** `/v1/chat/completions`
  from an external `llama-server`; it does not serve that endpoint.
- ARES's own code says so, in `gateway_streaming.py`: *"JaegerAI has no HTTP
  gateway — default to local bridge. Only try the legacy HTTP gateway path
  when the operator has explicitly configured one."*
- `status.py::_uncached_status()` checks the gateway first, but on any
  machine without `ARES_JAEGER_GATEWAY_URL` set it falls straight through to
  the bridge — which is every machine, by default.

So ARES↔Jaeger is **stdio-bridge-only in practice today**. The gateway code
is real and works, but it points at a server shape JaegerAI does not
currently ship — inherited from predecessor JROS.

This also bounds the review instruction to add "gateway/stdio parity"
tests: there is no live gateway to be at parity *with*. What can be pinned
is the shared translation contract, which
`tests/test_jaeger_event_contract.py` now does.

## Decision

The durable rule, replacing ADR-0001's wording:

> Independent workers run **out-of-process** and are reached through
> **adapters implementing a contract**. The transport — stdio subprocess,
> local HTTP, vendor SDK over HTTPS — is an adapter implementation detail,
> not the principle.

ADR-0001's substance is unchanged: no worker's execution loop is imported
into the ARES process (see ADR-0006 for the Jaeger case specifically). Only
the over-narrow "subprocesses" framing is retired.

On the gateway: it is **retained but reclassified as vestigial** — code kept
for a server shape that may return, not a current interface. It must not be
described as the baseline, planned for, or used to justify architecture
until JaegerAI ships a gateway. The local stdio bridge is the real ARES↔Jaeger
transport today.

## Consequences

Good:

- SDK-based cloud backends stop reading as violations of ADR-0001.
- Nobody plans daemon or transport work around a Jaeger HTTP server that
  does not exist. This alone invalidated part of a proposed roadmap.
- The scope of achievable Jaeger contract testing is stated honestly.

Costs:

- Vestigial gateway code carries upkeep and can mislead — as it did here,
  into two separate documents. If JaegerAI does not ship a gateway, a later
  ADR should decide whether to delete it outright rather than leave it
  ambiguous a third time.
- ARES's error text still tells operators to run `jaeger gateway`
  (`gateway_streaming.py::_bridge_error_message`). That message names a
  command that does not exist and should be corrected.

## What did not change

ADR-0006's actual decision stands: ARES reaches Jaeger only through the
versioned `JrosClient` contract and never imports its agent core. The
transports beneath that facade are what this ADR reclassifies.

ADR-0007's separation of boundaries also stands and is reinforced here:
browser↔ARES is WebSocket; ARES↔Jaeger is the stdio bridge. Neither
governs the other.

## Revisit if

JaegerAI ships an actual HTTP gateway or daemon. At that point the gateway
stops being vestigial, real gateway/stdio parity becomes testable, and the
"baseline interface" question ADR-0006 tried to answer becomes live for the
first time — with the multi-client, lifecycle, and security questions
ADR-0006 left open still unanswered and still blocking.
