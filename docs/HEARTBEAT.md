# Autonomous heartbeat in one anchor session

Keeps a single persistent session as the place where your conversation *and* the
agent's autonomous work both live, instead of scattering runs across disposable
sessions.

## Why not a cron schedule

ARES deliberately quarantines scheduled runs away from your chat:

| Behaviour | Where |
|---|---|
| Runs get their own `cron_<job_id>_*` session, one bucket per job | `api/schedules_store.py:699` |
| Those sessions are reassigned into a separate cron *project* | `api/cli_session_import.py:218-233` |
| They are hidden from the sidebar by default (`show_cron_sessions: False`) | `api/config.py:8910` |

That is the schedule system working as designed — automation stays out of your
timeline. An anchor session wants the opposite, so the heartbeat uses the normal
chat path instead of fighting three subsystems.

`POST /api/chat/start` is the exact call the WebUI composer makes
(`fastapi_app/schemas.py:399`). Posting to it means the tick is indistinguishable
from you typing: same transcript, same bridge continuity key, same memory, and
streaming/SSE/sidebar all work with no special-casing.

## Staying quiet

A 15-minute cadence would bury the session in heartbeat prompts, so every tick
polls `GET /api/kanban/stats` first and **exits without writing** unless a task
sits in `ready` or `todo`. Quiet periods leave no trace at all. `--always`
overrides the gate.

A second guard checks `is_streaming` on the anchor session and skips the tick
while a turn is already in flight, so a slow task cannot stack ticks.

## Setup

1. **Create the anchor session** in the WebUI (e.g. `Main-Workspace`), pin it,
   and copy its `session_id`.

2. **Dry-run it** — this touches nothing:

   ```bash
   cd services/controller
   ./.venv/bin/python scripts/heartbeat.py --session <session_id> --dry-run
   ```

3. **Install the timer:**

   ```bash
   cd services/controller/scripts
   sed -e "s|__PYTHON__|$PWD/../.venv/bin/python|" \
       -e "s|__SCRIPT__|$PWD/heartbeat.py|" \
       -e "s|__SESSION__|<session_id>|" \
       com.ares.heartbeat.plist.template > ~/Library/LaunchAgents/com.ares.heartbeat.plist
   launchctl load ~/Library/LaunchAgents/com.ares.heartbeat.plist
   ```

   Logs land in `/tmp/ares-heartbeat.log` and `/tmp/ares-heartbeat.err`.
   Remove with `launchctl unload`.

## Configuration

| Variable | Meaning |
|---|---|
| `ARES_ANCHOR_SESSION` | anchor `session_id` (required) |
| `ARES_BASE_URL` | default `http://127.0.0.1:$ARES_WEBUI_PORT` (port default `8788`) |
| `ARES_HEARTBEAT_PROMPT_FILE` | override the built-in prompt |
| `ARES_AUTH_TOKEN` / `ARES_CSRF_TOKEN` | only when WebUI auth is enabled |

With auth disabled, `require_mutation_identity` short-circuits
(`fastapi_app/request_context.py:158`) and no credentials are needed.

## If you later want it in the Schedules panel

Threading a target session through the scheduler is small — `create_job` builds a
flat dict (`api/schedule_jobs.py`), and `run_job` needs
`job.get("session_id") or f"schedule:{job['id']}"` (`api/schedule_scheduler.py:37`);
`run_turn`'s second parameter already *is* `session_id`
(`fastapi_app/adapters/frameworks.py:127`).

The unverified part is persistence: `_run_cron_job_in_profile_subprocess` runs
under a separate profile home, so whether rows land in a non-`cron_` session
needs testing. Take that path only if you want pause/resume/history in the UI.
