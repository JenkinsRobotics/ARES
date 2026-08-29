# ARES

ARES is a local automation controller for independently owned AI agents. It
defines identities, goals, schedules, budgets, permissions and approvals, then
wakes Hermes or JaegerAI through explicit adapters and evaluates the result.

ARES is not a chat agent, model runtime, shared memory store, or WebUI clone.
Hermes and Jaeger retain their own tools, sessions, memory and credentials.

## Quick start

```bash
git clone https://github.com/JenkinsRobotics/ARES.git
cd ARES
cd services/controller
.venv/bin/python -m uvicorn fastapi_app.main:app --host 127.0.0.1 --port 8788
```

Open `http://127.0.0.1:8788` for the lightweight agent/goal/run/approval
dashboard. It also links to Hermes (`8787`) and Jaeger (`8790`). Keep ARES on
loopback; network exposure is opt-in and requires authentication.

## Runtime topology

- Hermes Agent + Hermes WebUI: stable Apple container, port `8787`.
- JaegerAI + its Hermes-WebUI-derived interface: native macOS, port `8790`.
- ARES controller dashboard: native during development, port `8788`.
- Ollama and all downloaded model weights: Mac host, independently consumed by
  both agents.

Sharing tools, memory, sessions or credentials is denied unless an explicit,
scoped grant exists. Credentials are represented only by opaque Keychain
references.

## Repository map

- `services/controller/apps/dashboard/static/` — minimal controller dashboard
- `apps/macos/` — Swift macOS shell and native tools
- `services/controller/` — FastAPI controller and tests
- `integrations/` — versioned runtime/provider adapters
- `core/` — ARES-owned authority and package boundary
- `docs/` — current architecture, API, security, and decisions

Runtime inventory and capability status are calculated dynamically. Query the
authenticated `/api/inventory` endpoint instead of relying on documented counts.

See `docs/vision.md`, `docs/architecture.md`, `docs/development.md`, and
`docs/api.md`.
