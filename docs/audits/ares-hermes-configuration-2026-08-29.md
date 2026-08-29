# ARES Hermes-configuration audit — 2026-08-29

Scope: the minimal automation controller and the live Hermes WebUI at
`127.0.0.1:8787`. This audit covers identity and workspace configuration, not
the correctness of model responses or autonomous goal evaluation.

## Finding

Before this change ARES could pass an identity string and workspace path to a
Hermes run, but it could not inspect or configure Hermes's durable identity or
workspace registry. The run adapter only invoked the `hermes` launcher. The
dashboard's `Configured` label therefore described an ARES agent definition,
not proven Hermes runtime configuration.

ARES now owns a desired configuration request and approval record while Hermes
continues to own the effective `SOUL.md` and workspace registry. The adapter
uses Hermes WebUI's public runtime API, applies workspace registrations before
the identity document, compensates workspace additions if a later write fails,
and reads the effective state back before recording success.

## Component evidence

| Component | Status | Evidence |
|---|---|---|
| Runtime configuration contract | Real | `services/controller/core/automation/adapters.py:49-53` defines inspect/apply without giving ARES a runtime-state path. |
| Hermes configuration client | Real | `services/controller/core/automation/adapters.py:88-161` uses bounded JSON HTTP calls to Hermes WebUI and verifies effective state. |
| Desired-state validation | Real | `services/controller/core/automation/service.py:304-331` bounds SOUL size and restricts workspace paths to the approved `/workspace` mount. |
| Approval gate | Real | `services/controller/core/automation/service.py:60-91` persists a pending change and approval before mutation; approval resolution leases and applies it. |
| Durable evidence | Real | `services/controller/core/automation/service.py:333-344` stores a SOUL digest, endpoint owner, and effective workspace paths, not runtime credentials. |
| Public API | Real | `services/controller/fastapi_app/routers/automation.py:47-67` exposes inspect and approval-request routes. |
| Dashboard | Real | `services/controller/apps/dashboard/static/app.js:31-46` shows Configure for Hermes; lines 71-81 and 101-114 implement inspect and submit. |
| Host mount reconciliation | Missing by design | Workspace registration accepts only container paths already under `/workspace`; Apple-container recreation is not implemented in this slice. |

## Security and correctness review

- Raw credentials are not accepted or copied. An authenticated Hermes WebUI
  will reject ARES until a separate opaque authentication contract exists.
- Mac host paths are rejected instead of being mistaken for container paths.
- Agent identifiers are restricted to a bounded safe character set before the
  dashboard interpolates them into action handlers.
- Configuration is add-only for workspaces; an omitted path is not removed.
- One pending/applying configuration change is allowed per agent. Approval
  resolution leases the change before making the external call.
- Restart during apply is marked failed and requires inspection before retry,
  because an external runtime write cannot be assumed atomic with ARES state.
- ARES stores the desired SOUL because identity policy is controller-owned. It
  stores only a digest of the verified effective SOUL in application evidence.

## Verification performed

```text
./scripts/test.sh -q tests/test_automation_controller.py
12 passed in 38.21s

.venv/bin/ruff check core/automation fastapi_app/routers/automation.py \
  tests/test_automation_controller.py
All checks passed

Live read-only adapter probe:
owner=hermes, endpoint=http://127.0.0.1:8787,
workspaces=[/workspace], SOUL length=513

Live idempotent verification:
existing SOUL and /workspace were submitted as desired state;
the adapter reported soul_unchanged=true and verified the workspace registry.

Live approved ARES change:
change=config_c9161c34096b440f, approval=approval_95ad51decad14258,
status=applied, effective SOUL sha256=
9ee1606c0d5f7f1086421d4ba886974810b792afef23cdd0c91334319d02557d,
effective workspaces=[/workspace]. The same digest was read independently from
Hermes WebUI after application.
```

## Remaining risks

1. Password/passkey-protected Hermes configuration needs an explicit,
   non-exporting authentication broker; ARES must not scrape browser cookies.
2. Adding Mac folders to the Apple container still requires a separate,
   approval-gated infrastructure adapter and safe container replacement.
3. Hermes WebUI's configuration API is not explicitly version-negotiated yet;
   a future upstream route change will fail closed but needs a capability/version
   handshake before this can be called stable.
