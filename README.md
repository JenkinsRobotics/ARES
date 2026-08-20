# ARES

ARES is the Jenkins Robotics assistant product UI and controller. It presents
one consistent workspace while JaegerAI supplies the canonical agent runtime.

## Quick start

```bash
git clone https://github.com/JenkinsRobotics/ARES.git
cd ARES
bash install.sh
./start.sh
```

Open `http://127.0.0.1:8788`. Network exposure is opt-in and requires
authentication.

## Repository map

- `apps/web/static/` — browser UI
- `apps/macos/` — Swift macOS shell and native tools
- `services/controller/` — FastAPI controller and tests
- `integrations/` — versioned runtime/provider adapters
- `core/` — ARES-owned authority, memory, and orchestration
- `docs/` — current architecture, API, security, and decisions

Runtime inventory and capability status are calculated dynamically. Query the
authenticated `/api/inventory` endpoint instead of relying on documented counts.

See `docs/vision.md`, `docs/architecture.md`, `docs/development.md`, and
`docs/api.md`.
