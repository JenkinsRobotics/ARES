# ADR-0007: Browser chat streaming is WebSocket; SSE is compatibility only

**Status:** Accepted
**Date:** 2026-08-12
**Supersedes:** [ADR-0005](./0005-sse-streaming.md)
**Corrects:** [ADR-0006](./0006-jaeger-access-boundary.md), "Note on transport"

## Context

ADR-0005 states that "the browser opens `EventSource('/api/chat/stream?stream_id=…')`."
That is not true, and — this is the important part — **it was not true when
ADR-0005 was written.**

On 2026-07-22, the date ADR-0005 records for itself, `chat-stream.ts` already
called `new WebSocket(...)`. ADR-0005 was written "retroactively" and captured
the streaming decision ARES *inherited from upstream Hermes WebUI*, without
checking whether ARES still implemented it. Its reasoning about SSE's merits is
sound as a description of the upstream choice; it simply never described ARES.

Current state, verified:

- `apps/web/src/shared/chat-stream.ts` — `subscribeToChatStream()` opens a
  `WebSocket`, with reconnect/`lastEventId` resume. No `EventSource` appears
  anywhere in `apps/web/src/`, and there is no SSE fallback in that module.
- `fastapi_app/routers/realtime.py:162` — `@router.websocket("/api/chat/stream")`
  is the live chat transport.
- `fastapi_app/routers/realtime.py:305` — `@router.get("/api/chat/stream")`
  remains, docstring: *"Compatibility transport for pre-WebSocket clients."*
  SSE is still used broadly for other event streams (session activity,
  terminal, etc.).

This mattered immediately. ADR-0006 cited ADR-0005 as settled precedent to
argue against adding a WebSocket transport — resting on a record that never
matched the code. That citation compounded a second error, below.

## The two streaming boundaries are not the same decision

ADR-0005 governs one boundary; ADR-0006 was reasoning about another. Naming
both explicitly, because conflating them is what produced the error:

| Boundary | Transport | Governed by |
|---|---|---|
| browser ↔ ARES controller | **WebSocket** (SSE compatibility route retained) | this ADR |
| ARES ↔ JaegerAI | gateway HTTP + SSE relay, or local stdio bridge | [ADR-0006](./0006-jaeger-access-boundary.md) |

A conclusion about how the browser reaches ARES carries no authority over how
ARES reaches Jaeger. ADR-0006's "Note on transport" applied the former to the
latter and is corrected accordingly.

## Decision

Browser chat streaming is **WebSocket**. The SSE route at
`realtime.py:305` is retained as a compatibility transport for pre-WebSocket
clients and is not the default path.

ADR-0006's substantive conclusion is unchanged and still stands: **do not add
an ARES↔Jaeger WebSocket transport merely because Jaeger's protocol docs
mention one.** That conclusion rests on the ARES↔Jaeger gateway already
existing, not on ADR-0005. What is withdrawn is only the supporting citation —
specifically ADR-0006's claim that ADR-0005 "already chose SSE ... that still
holds," and its repetition of ADR-0005's warning that `realtime.py`'s WebSocket
route "should not be treated as a second parallel implementation." That route
is now the primary chat transport, not a parallel one.

## Consequences

Good:

- The record matches the code. An agent reading `chat-stream.ts` and the ADRs
  together no longer finds them in contradiction.
- The browser↔ARES and ARES↔Jaeger boundaries are separated, so a future
  transport decision on one cannot be justified by precedent from the other.
- ADR-0005's genuine content is preserved as history: it documents why
  *upstream Hermes WebUI* chose SSE, which remains useful context.

Costs:

- Two streaming transports are maintained on the browser boundary. The SSE
  route is compatibility surface with real upkeep; if no pre-WebSocket client
  exists, it is dead weight and should be retired by a later ADR rather than
  left ambiguous.
- WebSocket reconnect/resume correctness (`lastEventId`, `MAX_RECONNECTS`) is
  now load-bearing for chat and needs test coverage commensurate with that.

## Note on retroactive ADRs

ADRs 0001–0005 are all marked "recorded retroactively." At least one of them
described an inherited decision rather than the implementation. Before citing
any retroactive ADR as binding, verify it against the code it claims to
describe. A record that was never true is more dangerous than a missing one,
because it is quoted with confidence — as happened here, within hours of these
ADRs being restored.

## Revisit if

The compatibility SSE route is confirmed to have no remaining clients (retire
it), or a measured requirement appears that WebSocket cannot serve on the
browser boundary.
