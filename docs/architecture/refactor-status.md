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
