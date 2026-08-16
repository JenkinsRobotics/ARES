# ADR-0009: Framework adapters are the canonical execution registry

**Status:** Accepted; collected-turn seam implemented, broader consolidation in progress
**Date:** 2026-08-12

## Context

ARES has two independent ways to execute a worker turn, and they have
drifted into separate implementations of the same thing.

**Registry B — framework adapters** (`fastapi_app/adapters/frameworks.py`)
carries all real user chat:

    ares-context.tsx::sendMessage → POST /api/chat/start → realtime.py
      → RealtimeService.start_chat → adapters.for_session
      → JaegerAdapter → JaegerBackend.run_turn

**Registry A — `BackendRegistry` / `DispatchService`**
(`integrations/workers/cli_backends.py`, `api/dispatch_service.py`) carries
SI plan execution: `api/schedule_scheduler.py` calls
`get_dispatch_service().dispatch_turn(...)` to resume paused multi-step
plans. That is a real feature, not dead code — so this is not simply a
matter of deleting one side.

The cost of the split is concrete and was paid during this session:

- Two classes both claimed `jaeger_local` (`JaegerBackend` via Registry B,
  `JaegerAIBackend`/`JaegerWorker` via Registry A). Whichever module
  imported last silently won.
- A transport bug was fixed in Registry A's Jaeger path while Registry B —
  the one carrying every real user message — used a different code path
  entirely.
- Seven CLI backends were registered with `BackendRegistry` while
  `CliFrameworkAdapter` instantiates the same classes from its own hardcoded
  map, independent of that registry.
- `POST /api/dispatch/chat/start` has no frontend caller, and its docstring
  advertised an `ARES_CHAT_VIA_DISPATCH=1` "transparent mode" that was never
  implemented (the variable is read nowhere). Its handler also accepts
  `connection_id`, `workspace`, `profile` and `personality` and ignores all
  four.

So the SI pipeline — planner, orchestrator, evaluator, trust engine — is
written, tested, and **not in the live chat path at all**.

## Decision

**The framework adapter layer (`fastapi_app/adapters/`) is canonical.**
It is the single implementation of "run a turn on worker X."

`DispatchService` keeps its distinct job — planning, evaluation, trust
gating, plan resumption — but stops carrying its own worker-execution
implementation. Where it needs a turn executed, it invokes the adapter
layer rather than `BackendRegistry`.

Rationale, in order of weight:

1. Registry B already carries 100% of real user traffic. Making the
   *unused* path canonical would migrate the working one onto the less
   exercised one.
2. Registry B is the layer that already owns streaming, cancellation,
   session binding, and the run journal — the parts hardest to reimplement
   correctly, and exactly what Registry A's path lacks.
3. It preserves the architecture-boundary test
   (`test_fastapi_chat_service_and_router_have_no_framework_imports`), which
   constrains what may import what.
4. One Jaeger implementation means a fix like this session's transport
   repair lands once, for both chat and scheduled plans.

## Consequences

Good:

- One implementation per worker. Registry-disagreement bugs become
  structurally impossible rather than a thing to remember.
- Scheduled plans and user chat get identical worker behaviour, streaming,
  and journaling for free.
- The SI pipeline becomes wirable in front of the real chat path, because
  both sides would finally speak the same execution interface.

Costs:

- `DispatchService` currently calls `worker.run_turn(...)` on
  `AgenticBackend` instances; adapters expose a different, richer interface
  (streaming, sessions, profiles). The seam needs designing — this is the
  actual work, and it is why this ADR authorises no code yet.
- `BackendRegistry` cannot simply be deleted: `AgenticBackend` subclasses are
  what adapters wrap. What is retired is the *second execution path*, not
  the backend classes.

## Sequencing

Do not start with the migration. In order:

1. Retire the misleading surface: the unimplemented transparent-mode claim
   is already removed. `/api/dispatch/chat/start` was subsequently retired:
   it had no supported caller and wrote replay data to the wrong journal. It
   is not the seam for step 3.
2. The adapter-invocation seam now exposes collected turn execution alongside
   streaming. `DispatchService` calls it in production and focused tests prove
   that adapter failure does not fall back to the legacy registry.
3. `schedule_scheduler.py` plan resumption reaches that seam through
   `DispatchService`. Remove remaining compatibility injection once downstream
   tests no longer construct the legacy registry directly.
4. Only then consider putting the SI pipeline in front of the chat path —
   a separate product decision, not a refactor.

## Revisit if

The SI pipeline's requirements turn out to need an execution interface the
adapter layer genuinely cannot express. Convenience of the existing
`run_turn` signature is not such a reason — that is what the seam in step 2
is for.
