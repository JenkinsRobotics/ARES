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

## Licence and provenance

ARES is licensed **AGPL-3.0** (`LICENSE`).

It is a fork, not a from-scratch project. The browser UI and the controller
both descend from **Hermes WebUI** (MIT, © 2025 Hermes Web UI Contributors),
and the browser bundle redistributes KaTeX, js-yaml and streaming-markdown —
all MIT. MIT into AGPL-3.0 is a permitted one-way combination; the condition is
that the upstream notices travel with the code, which they do:

- `THIRD_PARTY.md` — what came from where, and what is merely talked to
- `apps/web/static/LICENSE`, `services/controller/LICENSE` — the retained MIT notice
- `apps/web/static/vendor/LICENSES.md` — notices for the bundled libraries

JaegerAI, JaegerOS and jaeger-agent (Apache-2.0) are **not** vendored here.
ARES reaches JaegerAI as a separate process over an NDJSON bridge.
