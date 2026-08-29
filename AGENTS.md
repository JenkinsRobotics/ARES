# ARES contributor contract

Read `DOCTRINE.md` before changing product behavior.

ARES is the product UI and controller. JaegerAI is the canonical agent runtime.
ARES may integrate other model providers and command-line workers, but it never
reads or writes another product's private state.

## Ownership

- JaegerAI owns agent turns, authoritative transcripts, tool calls, runtime
  history, skills, MCP configuration, credentials, models, and personas.
- ARES owns presentation, workspaces, projects, drafts, title overrides,
  pin/archive metadata, approvals UI, and combined projections.
- Cross-product operations use the versioned Jaeger bridge contract.
- Cross-product identifiers are canonical and opaque. Retired Hermes/JROS
  backend names, environment variables, browser keys, and session prefixes
  must not be reintroduced.

## Source map

- `apps/web/static/`: browser UI
- `apps/macos/`: native shell and native macOS tools
- `services/controller/`: FastAPI routes and product services
- `integrations/providers/jaeger/`: Jaeger bridge adapter
- `integrations/workers/`: other worker adapters
- `core/`: ARES-owned orchestration, memory, and authority code

## Rules

1. Never traverse or edit JaegerAI state, source, credentials, or configuration.
2. Never infer support from a runtime name or version; negotiate capabilities.
3. UI controls remain visible and explain unavailable capabilities unless an
   explicit user setting disables the feature.
4. Register routers, tools, skills, and capabilities once; inventory counts are
   calculated from live registries and health, never copied into docs.
5. Keep secrets out of JSON, messages, traces, logs, and API responses.
6. Bind to loopback by default. A network bind requires authentication.
7. Validate all workspace paths and fail closed on traversal.
8. Commit approved work locally; do not push unless asked.

## Verification

Read the implementation to understand it. Run the real system to prove it.
Test the production wiring to prevent regression. Do not claim "fully working",
"production ready", "end-to-end complete", or "session persistence works".
State the command, git commit, expected vs actual, and any mocked boundary.

User-visible promises, with current runtime evidence, code-path trace, gaps,
and mocked boundaries:
[`docs/verification/jaeger-five-promises-report.md`](docs/verification/jaeger-five-promises-report.md).

The evidence is time- and revision-scoped. Re-run
`services/controller/scripts/verify_jaeger_promises.py` before repeating it;
never turn its last result into an unqualified standing claim.

A test file does not lock a promise it does not exercise. When adding one here,
say which of the two it is.

A unit test that sets `is_gateway=True` on a fake backend only proves the
branch. Production proof is `JaegerBackend.get_worker_target()` plus a
multi-turn send on that backend.

```bash
cd services/controller
./scripts/test.sh -q tests/test_jaeger_production_promises.py
./scripts/test.sh -q tests/test_jaeger_attach_and_status_honesty.py
./scripts/test.sh -q tests/test_jaeger_ownership_literals.py
cd ../..
swift test
```

Use targeted controller tests for changed domains. The source guard rejects new
retired ownership names, personal paths, and direct JaegerAI state access.
