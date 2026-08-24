# Architecture refactor status (ARES pointer)

Canonical status lives in JaegerAI:

`../JaegerAI/docs/architecture/refactor-status.md`

ARES remains the experience/governance layer. It must not import
`jaeger_ai` / `jaeger_agent` / `jaeger_os` (see
`services/controller/tests/test_phase0_boundaries.py`).

## This checkout

- Isolation: `ARES_NO_JAEGER`, `ARES_WEBUI_PRESERVE_ENV`, credential strip
- Schedules: Jaeger authoritative when available; local jobs projected as `ares_local`
- Bridge: spawn `jaeger bridge`; talk NDJSON; do not open `state.db` from ARES
- Agent 3 (`8d32aab81`): onboarding is six implemented steps; Back from
  runtime returns to privacy; ARES is experience/governance, JaegerAI
  is the runtime. Frontend 61 passed.
- Agent 3 follow-up: onboarding copy no longer says Companion SI;
  Goals page can resolve/abandon Jaeger-owned indeterminate effects.
