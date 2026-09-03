# ARES

ARES is the Jenkins Robotics platform for creating and operating an
owner-defined persistent Synthetic Intelligence (SI). ARES is not the AI.
The SI belongs to its owner.

```
Owner → SI → reasoning / memory / planning → workers / models / tools → world
```

ARES owns the product and system experience: SI conversation, identity,
memory, permissions, and local infrastructure. Execution workers (including
JaegerAI) are replaceable resources, not personalities. Changing a model or
runtime must not destroy identity, memory, history, goals, or the owner
relationship. You talk to one SI. You do not pick a runtime per turn.

Public surface is **0.3.0 alpha**. That is `VERSION`. Do not treat the older
`v1.0.0` git tag as this product.

## Production UI

The live product UI is `services/controller/apps/dashboard/static`, served by
the controller at `http://127.0.0.1:8788`. `apps/web/static` is not the
production frontend.

## Repository map

- `core/` — SI identity, memory, planning, authority
- `services/controller/` — FastAPI controller and dashboard
- `apps/macos/` — native macOS shell
- `integrations/` — versioned worker / provider adapters

Durable workers currently registered in core: `claude`, `codex`, `gemini`,
`grok` (also `hermes`, `jaeger`, `openclaw` as independently owned products).
`pi` is not durable.

## Quick start

```bash
git clone https://github.com/JenkinsRobotics/ARES.git
cd ARES
bash install.sh
./start.sh
```

Open `http://127.0.0.1:8788`. Bind loopback. Network exposure is opt-in and
requires authentication.

## License

ARES is AGPL-3.0. See `LICENSE`, `CONTRIBUTING.md`, and `SECURITY.md`.
Preserve upstream notices, including Hermes-derived UI attribution in
`LICENSE`.
