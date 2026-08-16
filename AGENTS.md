# ARES — agent entry

**CRITICAL: Read [DOCTRINE.md](./DOCTRINE.md) first.** This file contains the first principles of the system. Any proposal that violates the Doctrine is invalid.

| | |
| --- | --- |
| **Port** | ARES UI + API: **8788** |
| **Not this repo** | hermes-webui (3rd-party) is `~/GitHub/hermes-webui` on **8787** — reference only |
| **Owner** | Jenkins Robotics / Matthew Jenkins |

Read this before changing code. Do not invent Board/Leo/hands/control-plane metaphors.

## What ARES is

ARES is the product UI + controller that replaces hermes-webui for daily use.
It talks to multiple backends through adapters (Jaeger AI primary local path,
Hermes Agent, Ollama, Claude, Codex, cloud). ARES owns sessions and product
state under `~/.ares/`. Workers are invoked; their stores are read-only.

## Folder map (where to edit)

```
ARES/
├── apps/web/                  # React UI (what you see in the browser)
│   └── src/
│       ├── features/chat/     # Chat page (messages, composer, send)
│       ├── components/shell/  # Frame: session list, drawers, workbench
│       ├── styles/
│       │   ├── chat-layout.css    # ★ padding / gaps / phone safe-area / toolbar
│       │   ├── shell-drawers.css  # ★ left/right mobile drawers
│       │   ├── settings-layout.css
│       │   └── island-backdrop.css
│       ├── index.css          # colors/tokens + imports the files above
│       └── shared/            # API contracts, translators, context
├── apps/macos/                # Native shell (WKWebView → :8788)
├── services/controller/       # FastAPI backend
├── integrations/              # Worker adapters (jaeger, hermes, ollama, …)
├── core/                      # SI / memory modules (not all on chat path yet)
└── docs/                      # Vision, architecture, ADRs, rfcs
```

### UI sizing and padding (non-coder)

| Change this look | Edit this file |
| --- | --- |
| Chat message list padding, composer safe-area, toolbar density on phone | `apps/web/src/styles/chat-layout.css` |
| Left/right drawers on phone | `apps/web/src/styles/shell-drawers.css` |
| Colors / theme tokens | `apps/web/src/index.css` |
| Chat behavior (send, backends, bubbles content) | `apps/web/src/features/chat/ConversationPage.tsx` |
| Session list | `apps/web/src/components/shell/SessionSidebar.tsx` |
| Overall 3-pane frame | `apps/web/src/components/shell/WorkspaceShell.tsx` |

## Rules

1. **Smallest slice only.** One concern per change (e.g. phone padding only).
2. **Research → plan in `~/Desktop/ARES-agent-docs/` → wait for go** before product code (unless user already said go/fix it).
3. **Do not edit hermes-webui** unless the task is explicitly about that repo.
4. **ARES writes only ARES state.** Worker DBs are read-only.
5. **UI uses ARES contracts** in `apps/web/src/shared/` — translate worker payloads at the boundary.
6. **No metaphor product language** in UI or new docs.
7. After an approved fix: **commit locally**; **do not push** unless asked.
8. Prove UI with `cd apps/web && npm run build` (and phone check for layout slices).

## Chat backend gate

In `ConversationPage.tsx`, selected backend must be:

`local selectedBackend || snapshot.selectedBackend || snapshot.connections selected id`

Empty local alone is not "no models."

## Docs to read by task

| Task | Read |
| --- | --- |
| Product intent | `docs/vision.md` |
| Runtime / adapters | `docs/architecture.md` + `docs/decisions/` |
| HTTP API | `docs/api.md` |
| Install / run | `docs/development.md` |
| Deep contracts | `docs/rfcs/` |

## Restart / recovery

`start_ares.sh` binds `0.0.0.0` so the phone can reach it over Tailscale.
`ctl.sh` defaults to `127.0.0.1` and **loads `services/controller/.env`, which
overrides the shell** — so starting through it while a `0.0.0.0` server is
already up leaves two listeners on 8788 and the phone talking to the older one.
Stop first, then start once.

```bash
# Stop everything on 8788 (both bind styles)
lsof -nP -iTCP:8788 -sTCP:LISTEN -t | xargs kill 2>/dev/null || true

# Start fresh, bound for phone access
cd ~/GitHub/ARES/services/controller && nohup bash ./start_ares.sh >/tmp/ares.log 2>&1 &

# Verify (expect exactly one listener, on *:8788)
lsof -nP -iTCP:8788 -sTCP:LISTEN
curl -sS http://127.0.0.1:8788/api/health
curl -sS http://100.74.2.15:8788/api/health   # Tailscale / phone
```

Full check: `./scripts/smoke_test.sh` (~1 min).

| Symptom | Fix |
| --- | --- |
| `jaeger_local` says `not_installed` | Read the `fix` field in the response — it names the variable or path at fault. Usually a stale `ARES_JAEGER_HOME`. |
| Two listeners on 8788 / phone sees stale UI | Run the stop command above, then start once via `start_ares.sh`. |
| `ctl.sh status` says stopped but chat works | Server was started outside ctl; ctl tracks only its own state file. Use `start_ares.sh` to restart. |
| Directives not applying | `curl -sS localhost:8788/api/ares/directives` — check `enabled` and `count`, then `~/.ares/directives.yaml`. |
| Send returns 409 | A turn is still running. Wait, or press Stop. A dead worker is reclaimed automatically on the next send. |

## Verification

```bash
cd apps/web && npm run typecheck && npm test -- --run && npm run build
cd services/controller && ./scripts/test.sh   # or targeted pytest
```

Start ARES: `./start_ares.sh` or `./start.sh` with **background** for agents — port **8788**, bind `0.0.0.0` for phone.
