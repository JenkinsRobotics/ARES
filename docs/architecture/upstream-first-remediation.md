# Upstream-first remediation record

Date: 2026-08-25

This record covers the reliability changes shared by ARES and JaegerAI. It
implements the project's upstream-first policy without importing a second
controller or crossing the ownership boundary: Jaeger owns agent execution and
durable runtime state; ARES owns presentation and the versioned bridge adapter.

## Verified donor

| Source | Immutable revision | File / behavior used | Tests examined | License |
|---|---|---|---|---|
| NousResearch/hermes-agent | `b0cf2597c2dbb9dacd5c4f063ae7e71587f02c2e` | `gateway/relay/ws_transport.py`: request IDs, a pending-future map, one receive-side dispatcher, timeout cleanup | Transport request/response behavior and local ARES concurrency regression | MIT, repository `LICENSE` |

No source code from proprietary ChatGPT, Claude Code, Grok, or Antigravity
internals was claimed or copied. Their product behavior may be used only as a
behavioral target when an exact official public source file, revision, tests,
and compatible license are independently verified.

## Decisions

| Local defect | Decision | Implementation and deviation |
|---|---|---|
| ARES queries waited behind a complete Jaeger model turn | `ADAPTED_UPSTREAM` | Adapted Hermes' one-reader/request-ID pending-map pattern to synchronous NDJSON and `queue.Queue`. ARES still permits one model turn at a time, but queries and commands are independently routed. A 30-second bounded request timeout was added. |
| Parallel tool batches exceeded the documented 24-call cap | `LOCAL_IMPLEMENTATION` | The local loop now slices a batch to the remaining budget before dispatch and emits synthetic non-executed results for refused calls. Hermes' own limit is a useful precedent but its value and execution contract do not match Jaeger. |
| ARES inferred runtime failure from assistant prose | `LOCAL_IMPLEMENTATION` | Jaeger now emits additive `halt_reason` and stable `halt_code` fields; ARES goal continuation consumes only the structured code. No prose regex participates in continuation decisions. |
| `success: false` counted as successful when `ok` was absent | `LOCAL_IMPLEMENTATION` | Jaeger's central completion observer now treats either explicit false field as failure. |
| Trace and latency logs retained prompt, response, tool detail, and session text | `LOCAL_IMPLEMENTATION` | Diagnostic logs now retain counts, timing, tool names, and truncated hashes only; episodic memory remains a separate operator-enabled product feature. Active diagnostic files are mode `0600`; trace joins daily rotation. |
| Manual Dream/Wonder execution was rejected as recent user activity | `LOCAL_IMPLEMENTATION` | The idle gate now applies only when `automatic=True`, and activity uses a monotonic clock. Manual API/tool invocation remains explicit operator intent. |
| Swift showed a mode change before bridge acknowledgement | `LOCAL_IMPLEMENTATION` | UI state changes only after `sendChat` succeeds; failure preserves the previous mode and displays an error. |

## Acceptance evidence

- A query result completes while a model turn remains in flight.
- The tool-call breaker fires at exactly the configured cap, not one call later.
- A reply can carry `halt_code` without a protocol-version bump because the
  fields are additive and omitted on clean completion.
- Ordinary prose containing timeout-like wording cannot pause a goal without a
  structured halt code.
- Trace rows do not contain input text or session identifiers and are created
  with owner-only permissions.

## Remaining upstream-first queue

Before changing cancellation, approval storage, sandboxing, hook execution, or
resumable runs, create a separate decision row with an immutable upstream pin.
Priority order is correctness/recovery, security/privacy, bounded cancellation,
backpressure, safe observability, small-model compatibility, maintainability,
performance, then UI polish.
