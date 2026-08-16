# Architecture Decision Records

Short records of decisions that shape the ARES runtime, and the reasoning behind
them. They exist so the next maintainer — human or agent — does not have to
re-derive intent from code, or silently reverse a decision that was deliberate.

Write one when a choice is **load-bearing and non-obvious**: something a reasonable
person would otherwise "fix" the other way.

| ADR | Decision |
|---|---|
| [0001](./0001-subprocess-workers.md) | ~~Workers run as subprocesses~~ — superseded by 0008 |
| [0002](./0002-two-store-model.md) | ARES owns its store; workers own theirs |
| [0003](./0003-read-only-means-no-write-back.md) | `read_only` marks absence of a write-back path |
| [0004](./0004-translator-layer.md) | Frontend consumes ARES contracts, never framework shapes |
| 0005 | ~~Streaming uses SSE~~ — superseded by [0007](./0007-chat-streaming-is-websocket.md) |
| [0006](./0006-jaeger-access-boundary.md) | JaegerAI is reached through its contract, never imported |
| [0007](./0007-chat-streaming-is-websocket.md) | Browser chat streaming is WebSocket; SSE is compatibility only |
| [0008](./0008-worker-access-and-the-vestigial-gateway.md) | Workers reached via adapters; Jaeger's HTTP gateway is vestigial |
| [0009](./0009-canonical-execution-registry.md) | Framework adapters are the canonical execution registry |
| [0010](./0010-inference-versus-delegation.md) | Model inference and agent delegation are different operations |
| [0011](./0011-cli-delegation-has-no-session-continuity.md) | CLI agent delegation is single-turn; only Hermes resumes |

Format: context, decision, consequences, and what would justify revisiting it.

## These records are load-bearing — do not delete them

ADRs 0001–0005 were deleted during a docs reorganization in 2026-08. Within
weeks, three separate agents re-derived and re-litigated ADR-0001's decision
(workers out-of-process) from scratch, because the reasoning no longer existed
anywhere in the repo. Restoring them is what ADR-0006 documents.

An accepted ADR is superseded by a newer ADR that says so — never by deletion,
and never by silently building the other way. If one looks obsolete, check its
"Revisit if" clause first: several of these anticipate the exact objection that
tends to reopen them.

Paths in 0001–0005 predate the `api/backends/` → `integrations/workers/` move
(and `frontend/` → `apps/web/`) and are left as written; ADRs are historical
records, not living documents.

## Verify a retroactive ADR before citing it

ADRs 0001–0005 are all marked "recorded retroactively." ADR-0005 turned out to
be **inaccurate on the day it was written** — it documented an inherited
upstream decision rather than ARES's actual implementation, and was cited as
binding within hours of these files being restored. See ADR-0007.

A record that was never true is more dangerous than a missing one, because it
gets quoted with confidence. Check a retroactive ADR against the code it
claims to describe before relying on it.

Known open corrections: none outstanding.

ADR-0003 was verified on 2026-08-12 and **still holds** — its semantic ("does
ARES have a supported append path?") exactly matches the code. See ADR-0011,
which confirms there is no append path for the CLI delegation backends and
records why.
