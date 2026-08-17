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
- Compatibility identifiers exist only in
  `integrations/providers/jaeger/legacy_compat.py` and the one-time browser
  storage migration.

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

```bash
cd services/controller
./scripts/test.sh -q tests/test_jaeger_ownership_literals.py
cd ../..
swift test
```

Use targeted controller tests for changed domains. The source guard rejects new
retired ownership names, personal paths, and direct JaegerAI state access.
