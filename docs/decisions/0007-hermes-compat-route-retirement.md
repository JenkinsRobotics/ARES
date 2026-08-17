# 0007: Retire Hermes-era route ownership

Status: accepted (Phase 3, 2026-08-16)

`fastapi_app/routers/hermes_compat.py` is a temporary URL adapter for the
vanilla ARES WebUI. It does not own Jaeger state. Every retained endpoint must
delegate to an ARES service or the versioned Jaeger bridge contract.

## Route inventory

| Endpoint | Classification | Decision |
| --- | --- | --- |
| `GET/POST/DELETE /api/providers` | Must route through Jaeger | Retained URL; credential names and mutations use Jaeger's credential service. Secret values never return to ARES. |
| `POST /api/providers/delete` | Must route through Jaeger | Retained URL; delegates to Jaeger's validated delete command. |
| `GET /api/providers/self-hosted` | Still required by ARES UI | Retained as an ARES-owned local-runtime probe. |
| `GET /api/default-model` | Still required by ARES UI | Retained as an ARES settings projection. |
| `POST /api/models/refresh` | Replaced by native ARES service | Retained URL adapter; delegates to the native runtime-filtered model catalog. |
| `POST /api/personality/set` | Replaced by native ARES service | Retained until its remaining command-palette caller migrates. |
| `GET /api/notes/search` | Replaced by native ARES service | Retained URL adapter to ARES notes. |
| `GET /api/onboarding/probe` | Replaced by native ARES service | Retained URL adapter to ARES onboarding state. |
| `POST /api/onboarding/complete` | Replaced by native ARES service | Retained URL adapter to ARES onboarding state. |
| `GET /api/updates/summary` | Replaced by native ARES service | Retained URL adapter to ARES update state. |
| `GET /api/background` | Replaced by native ARES service | Retained read projection; background mutation is owned by the native controls router. |
| `GET /api/goal` | Replaced by native ARES service | Retained read projection; goal mutation is owned by the native controls router. |
| `GET /api/wiki/browse` | Replaced by native ARES service | Retained URL adapter to ARES wiki. |
| `GET /api/channels` | Safe to remove | Removed; no production caller. |
| `GET /api/messaging/platforms` | Safe to remove | Removed; no production caller. |
| `POST /api/model/set` | Replaced by native ARES endpoint | Removed duplicate; `routers/models.py` is authoritative. |
| `POST /api/profile/switch` | Replaced by native ARES endpoint | Removed duplicate; `routers/profiles.py` is authoritative. |
| `POST /api/profile/create` | Replaced by native ARES endpoint | Removed duplicate; `routers/profiles.py` is authoritative. |
| `POST /api/profile/delete` | Replaced by native ARES endpoint | Removed duplicate; `routers/profiles.py` is authoritative. |
| `POST /api/session/new` | Replaced by native ARES endpoint | Removed duplicate; `routers/session.py` and the session contract are authoritative. |
| `POST /api/transcribe` | Replaced by native ARES endpoint | Removed obsolete 501 stub; `routers/uploads.py` is authoritative. |
| `POST /api/share/create` | Replaced by native ARES endpoint | Removed duplicate; `routers/shares.py` is authoritative. |

## Boundary rules

- Jaeger installation and runtime paths are resolved only by
  `integrations/providers/jaeger/paths.py`.
- ARES does not read or write Jaeger credential files. It may list credential
  names and request set/delete operations through the bridge.
- ARES does not write Jaeger configuration files. Model changes are requested
  through Jaeger's validated `configure_model` command.
- ARES may retain explicit, read-only Hermes import adapters for historical
  migration, but those adapters cannot become active runtime ownership paths.
