# ADR-0010: Model inference and agent delegation are different operations

**Status:** Accepted (vocabulary and contract split); routing not yet built
**Date:** 2026-08-12

## Context

ARES can do two very different things that today share one ambiguous
model/provider selector:

**Model inference** — "generate the next tokens." The orchestration, tools,
context, and session belong to ARES or to Jaeger; only token generation is
outsourced. Implemented by `ClaudeCloudBackend` (Anthropic SDK, streaming),
`OpenAICloudBackend`, `XAICloudBackend`, `OllamaLocalBackend`, and by
Jaeger's own `external_model` config block.

**Agent delegation** — "hand this whole task to another agent." The other
agent runs its *own* tool loop, its own context window, its own session,
and returns a result. Implemented by `ClaudeLocalBackend` (`claude -p`),
`CodexLocalBackend` (`codex exec`), `GrokLocalBackend`, and Hermes.

These are not interchangeable, and the difference is user-visible:

- Cost and latency differ by an order of magnitude.
- Delegation runs a tool loop with filesystem and shell access on the user's
  machine; inference does not.
- Delegated context is invisible to ARES — ARES sees a result, not the
  reasoning, and cannot journal what the other agent did internally.
- "Claude" means both `ClaudeCloudBackend` and `ClaudeLocalBackend`. Picking
  "Claude" in a model dropdown is ambiguous today, and the two have
  materially different privileges.

The registry split (ADR-0009) hid this: both live behind
`BackendRegistry`/`AgenticBackend` with the same `run_turn(message,
session_id)` signature, which makes two different operations look like one.

## Decision

Treat these as **two named operations with separate contracts and separate
UI vocabulary.** They may share the adapter registry, but must not share a
selector, a config key, or a label.

- *Inference* answers "which model generates tokens for this turn."
- *Delegation* answers "which agent runs this task end to end."

Concretely, before routing is built:

1. Each adapter declares which operation(s) it supports — a capability on
   the adapter contract, not inferred from its name or class module.
2. Distinct UI surfaces. A model picker offers inference targets. Delegation
   is an explicit action ("hand this to Claude Code"), never an entry in the
   model dropdown.
3. Distinct config keys, so "which model does Jaeger reason with" and "which
   agent do we delegate coding tasks to" cannot overwrite each other.
4. Delegation results are journaled as delegated work, with the delegate
   named — ARES must not present another agent's output as its own turn.

Automated routing ("decide which of the two this task needs") is explicitly
**out of scope** here. Naming the operations correctly is a precondition for
building it, not the same work.

## Consequences

Good:

- Removes the ambiguity that makes "use Claude" underspecified.
- The privilege difference becomes explicit, which is a prerequisite for the
  authorisation model ADR-0006 left open — delegation grants another agent a
  tool loop on this machine, and that should be a deliberate act.
- Cost attribution becomes possible per operation type rather than per
  vaguely-named backend.

Costs:

- More surface than one "pick a model" control. This is honest complexity:
  the two operations really are different, and collapsing them is what
  created the confusion.
- Existing adapters need the capability declaration added.

## Revisit if

A single unified operation genuinely emerges — for example if delegation
targets start exposing token-level streaming, tool visibility, and context
control equivalent to inference, such that the distinction stops being
user-visible. That is not the case for any current adapter.
