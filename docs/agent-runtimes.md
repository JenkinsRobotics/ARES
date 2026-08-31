# Agent runtimes

An **agent runtime** is an independently owned agent product that ARES routes
through an explicit adapter and treats its sessions, memory, tools, credentials,
and model policy as private.

`services/controller/core/runtimes.py` is the single source of truth for which
runtimes exist. Before it, the answer was hardcoded in nine places — including
two duplicate `Literal["hermes", "jaeger"]` definitions that could drift apart.

## Two taxonomies, deliberately separate

| | Agent runtime | Backend connection |
| --- | --- | --- |
| Defined in | `core/runtimes.py` | `api/backend_catalog.py` |
| Answers | "who can hold a durable goal, run lease, and approval" | "who renders this chat turn" |
| Contract | `core/automation/adapters.AgentAdapter` | `fastapi_app/adapters` |

They are not merged, because most chat backends are not agents ARES delegates
goals to. A runtime that *also* offers a turn-level connection links to it via
`RuntimeDefinition.backend_id`; the registry test asserts that id really exists,
which is what stops the old `jaeger` / `jaeger_local` drift from recurring.

## Classification

Every runtime declares:

- **`deployment`** — `host`, `container`, or `cloud`. This drives install and
  verification, not just labelling: a `container` runtime is only ever reached
  through its published loopback port, never by an on-PATH command.
- **`transport`** — `cli`, `http`, or `cli+http`.
- **`durable`** — whether it may currently hold goals, runs, leases, and
  approvals. Classification and promotion are separate steps.

## Current runtimes

| Runtime | Deployment | Durable | Reached by |
| --- | --- | --- | --- |
| `hermes` | container | ✅ | `hermes` launcher + WebUI on `127.0.0.1:8787` |
| `jaeger` | host | ✅ | native runner API on `127.0.0.1:8791`; owner UI on `127.0.0.1:8790` |
| `openclaw` | container | ✅ | `container exec ares-openclaw`, gateway on `127.0.0.1:18789` |
| `claude` | host | — | `claude` CLI |
| `codex` | host | — | `codex` CLI |
| `gemini` | host | — | `gemini` CLI |
| `grok` | host | — | `grok` CLI |
| `pi` | host | — | `pi` CLI |

The five non-durable entries are installed and classified but not yet promoted:
they are selectable as chat connections and are visible to routing, but they
have no `AgentAdapter`, so they cannot hold a goal.

## ARES is the dispatcher; runtimes are execution engines

The persistent conversation, routing policy, approval boundary, evidence, and
capability registry belong to ARES. Hermes, Jaeger, and OpenClaw are selectable
execution engines. No framework is hard-coded as "the dispatcher."

New dashboard threads use `routing_mode=dispatcher`. A direct `@agent` prefix
is an explicit operator override and changes only that route. The dispatcher
can be configured through `GET/PUT /api/dispatcher`:

- `automatic` selects only engines whose latest dispatcher benchmark passed
  every required probe on all three or more attempts;
- `fixed` pins an enabled engine while clearly reporting whether it is
  benchmark-qualified;
- `fast`, `balanced`, and `accurate` change the weighting of measured latency
  versus correctness without changing the 100% qualification gate.

Before any results exist, ARES uses the registry's configured fallback order
and labels the decision `provisional_unbenchmarked_fallback`. It never presents
an untested engine as qualified.

`GET /api/dispatcher/capabilities` returns deterministic A2A-shaped cards.
ARES builds these from its runtime registry and observed configuration; model
text is not authoritative. MCP tool discovery remains the result of the real
`initialize` and `tools/list` exchange.

Run the repeatable local-tool benchmark with:

```bash
services/controller/.venv/bin/python scripts/benchmark-dispatcher.py --attempts 3
```

Each attempt must pass capability registration, unknown-nonce file reading via
a read-only tool, same-owner session continuity, an unknown nonce supplied only
through ARES RAG, and clean completion. The script temporarily uses an Ollama
local model and restores every original Agent record in a `finally` block.

## Unified-memory policy

All local-model leases share one process-wide ARES lock, even when they target
different frameworks. The Ollama launch agent also uses one loaded model, one
parallel request, a bounded queue, flash attention, quantized KV cache, and a
90-second default keep-alive. This avoids two sets of model weights competing
for Apple unified memory while retaining a short follow-up window. Override the
defaults at installation time with `ARES_OLLAMA_KEEP_ALIVE`,
`ARES_OLLAMA_MAX_LOADED_MODELS`, `ARES_OLLAMA_NUM_PARALLEL`, and
`ARES_OLLAMA_MAX_QUEUE`.

Private ARES RAG excerpts are injected only for a model route explicitly
classified `local`. Cloud routes receive no private RAG block.

## Adding a runtime

1. Add a `RuntimeDefinition` to `RUNTIMES` with `durable=False`.
2. If it also serves chat turns, add the connection to `api/backend_catalog.py`
   first, then reference it as `backend_id`.
3. To promote it, implement an `AgentAdapter` (`probe`, `start_run`,
   `cancel_run`) and register it in `ADAPTER_TYPES`, then set `durable=True`.

`default_adapters()` raises at construction if a runtime is marked durable
without an adapter, so a half-finished promotion fails immediately with a clear
message rather than later at dispatch with a `KeyError`.

## OpenClaw specifics

`scripts/install-openclaw-container.sh` provisions the container. Three things
in it are non-obvious and easy to regress:

- **Bind mode.** OpenClaw's gateway binds loopback *inside* the container, which
  makes a published port unreachable. It must be set to bind mode `lan` — the
  config value, not the host alias `0.0.0.0`. That in turn makes token auth
  mandatory. Keychain service `ares-openclaw-gateway` is the owner source of
  truth; provisioning creates a mode-`0600` runtime copy inside OpenClaw's
  private state mount. The shell entrypoint loads it after startup, so
  `container inspect` exposes only the secret-file path, not the credential.
- **No `--user` or `--workdir`.** Unlike the n8n container, the image ships a
  non-root `node` user with pre-created `0700` state dirs, and Apple's runtime
  already maps bind-mount ownership back to the host user. The default CMD
  (`node openclaw.mjs gateway`) resolves relative to the image `WORKDIR`
  (`/app`); repointing it produces `Cannot find module '/workspace/openclaw.mjs'`.
- **Host Ollama address.** The container uses the stable
  `http://host.container.internal:11434` redirect. It must not use the raw
  `ipv4Gateway`: the subnet changes, and a loopback-only host listener is not
  reachable through that bridge address. Ollama remains unavailable to LAN and
  tailnet peers. OpenClaw keeps separate product lanes internally as
  `ollama-local` and `ollama-cloud-via-host`; the latter avoids OpenClaw's
  reserved direct-`https://ollama.com` provider semantics while preserving the
  owner-visible Ollama Cloud route.

The Homebrew `openclaw` on the host is left untouched. It is the user's own
interactive install with its own state directory; ARES neither manages nor
routes to it.
