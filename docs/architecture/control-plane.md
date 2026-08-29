# ARES control plane

ARES is the autonomous reasoning, configuration, and governance plane above
independently owned Hermes and Jaeger runtimes. It is not a third chat agent and
does not absorb either runtime's tools, transcript, memory, or credentials.

```mermaid
flowchart TB
    A[ARES control plane] --> C[Agent definitions]
    A --> P[Sharing and approval policy]
    A --> L[Closed-loop evaluation]
    C --> H[Hermes Agent]
    C --> J[JaegerAI]
    P --> H
    P --> J
    H --> O[Mac Ollama]
    J --> O
    H --- HW[Hermes WebUI]
    J --- JW[Jaeger-owned ARES-derived WebUI]
```

## Ownership

- Hermes owns its runtime, tools, sessions, memory, schedules, and WebUI.
- Jaeger owns its runtime, tools, sessions, memory, schedules, and browser UI.
- ARES owns agent definitions, policy decisions, explicit sharing grants,
  evaluations, approvals, budgets, and closed-loop control records.
- Ollama owns model serving. Model weights remain on the Mac.

## Isolation and sharing

Isolation is the default. A resource crosses an agent boundary only through a
versioned `SharingGrant` naming the resource, grantee, access modes, optional
expiry, and approval requirement. The evaluator fails closed when no exact
grant exists.

Credentials are never copied into definitions or returned as values. A grant
contains an opaque reference such as `keychain://ares/github/jaeger`. A future
credential broker resolves the reference only while performing an authorized
operation and never exposes the secret to a session transcript or browser.

## Automation API

- `GET/PUT /api/agents` lists and validates runtime definitions.
- `GET/POST /api/goals` manages durable objectives.
- `POST /api/agents/{id}/wake` leases one run for an agent.
- `GET /api/runs` and `GET /api/runs/{id}/events` expose immutable evidence.
- `POST /api/runs/{id}/cancel` cooperatively cancels active work.
- `GET/POST /api/approvals` keeps consequential effects fail-closed.
- `POST /api/control/pause`, `/resume`, and `/tick` control scheduling.

Mutating access uses the controller's existing identity and CSRF/authentication
dependency. The dashboard consumes these APIs; it is not a second executor.

Definitions, goals, runs, events and approval metadata are stored with mode
`0600` under `$ARES_HOME/automation/state.json` using an atomic replace.

## Development topology

- Hermes WebUI and Hermes Agent run in the stable Apple container.
- Jaeger bridge and its WebUI run natively from the JaegerAI working tree.
- ARES runs natively from its working tree while the control plane evolves.
- Browser access remains loopback-only locally and is published remotely only
  by authenticated Tailscale Serve routes. ARES stays local by default even
  when the two agent interfaces are published to the tailnet.

## Closed-loop boundary

ARES may observe, evaluate, request revisions, approve within policy, or pause
an agent. It must not fabricate a human approval. Consequential effects remain
approval-aware, inspectable, and attributable to a definition and policy
version. Heartbeats resume incomplete work, failed runs retry at most three
times with bounded exponential backoff, restart recovery records a checkpoint,
and an idempotency key prevents duplicate wakes.
