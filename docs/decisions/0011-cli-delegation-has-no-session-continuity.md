# ADR-0011: CLI agent delegation is single-turn; only Hermes resumes

**Status:** Accepted (records current behaviour and its limits)
**Date:** 2026-08-12
**Relates to:** [ADR-0003](./0003-read-only-means-no-write-back.md) (verified
by this pass), [ADR-0010](./0010-inference-versus-delegation.md)

## Context

ADR-0001 stated the continuation model for out-of-process workers:

> Continuation is achieved by asking the worker to resume its own session
> (`--resume <session_id>`), not by replaying history across the boundary.

and warned that *"a broken resume silently starts a new worker session and
loses context — this was a real bug."*

A verification pass found that claim is true for exactly one worker.

**Hermes resumes.** `integrations/providers/hermes/backend.py:306` and
`streaming.py:307` both build `--resume <session_id>`.

**The CLI delegation backends do not.** In
`integrations/workers/cli_backends_legacy.py`, `CliBackend.run_turn` has the
signature `run_turn(self, message, session_id, **kwargs)` — and
`session_id` appears nowhere in the method body. It is accepted and
discarded. `_build_args(cli, message, model)` is never given it, and no
`--resume` (or equivalent) is emitted by any of `ClaudeLocalBackend`,
`CodexLocalBackend`, `GeminiLocalBackend`, `GrokLocalBackend`,
`OpenCodeLocalBackend`, `CursorLocalBackend`, `PiLocalBackend`.

So every delegation to Claude Code, Codex, or Grok starts a **fresh,
contextless agent session**. This is not a broken resume; resume was never
implemented for these backends. The parameter's presence in the signature
makes it look as if it were.

## Decision

Record this as current, intended-for-now behaviour: **CLI agent delegation
is single-turn.** A delegated task must be self-contained, because the
delegate will not remember the previous one.

`session_id` stays in the signature — it is part of the `AgenticBackend`
contract that other backends do honour — but its being unused here is
documented rather than mistaken for a defect to be "fixed" by whoever next
reads the signature.

## Consequences

- Multi-turn delegated conversations silently lose context between turns.
  Any UI that presents delegation as an ongoing conversation is misleading;
  see ADR-0010, which separates delegation from inference precisely because
  their behaviour differs this much.
- ARES cannot currently offer "continue what Claude Code was doing." This is
  also the correct, consistent reason those imported sessions are
  `read_only` — which **verifies ADR-0003**: its semantic ("does ARES have a
  supported append path?") still exactly matches the code. There is no
  append path, so `read_only = true` for Claude Code / Codex / Gemini
  remains right for the reason ADR-0003 gave.
- Cost and latency are higher than they look: no warm session means full
  context re-establishment inside the delegate on every task.

## What would fix it

Each CLI exposes its own continuation mechanism and they do not agree —
`claude --resume <id>`, `codex` session flags, and so on differ per vendor.
Implementing this means per-adapter work plus somewhere to persist the
mapping from ARES session to delegate session. That is real work, not a
one-line flag, and should be scoped per adapter rather than attempted
generically.

Prefer, in order: a vendor SDK that exposes sessions as first-class objects
(see ADR-0010's note on integration quality) over hand-rolling `--resume`
string handling per CLI.

## Revisit if

Any delegation adapter gains real session continuity — at that point this
ADR is superseded for that adapter, and its `read_only` treatment under
ADR-0003 must be revisited in the same change, since the two are the same
question asked from different ends.
