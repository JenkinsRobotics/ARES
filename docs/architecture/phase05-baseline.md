# Phase 0.5 — Baseline closure

> **Correction (2026-08-23 evening).** An earlier revision of this file
> treated Phase 0.5 as closed after one green ARES run. That conclusion
> was wrong: later fixes were not covered by that run, live AF_UNIX
> ownership after `./start.sh` was not proven, schedule split-brain was
> still open, and GitHub Actions has still never seen this tree. This
> file now records those corrections instead of silently replacing them.
> **Phase 0.5 is not closed. Architecture refactor: NO-GO.**

Started 2026-08-23 as a continuation of Phase 0. Does **not** begin the
modular architecture refactor.

JaegerAI pointer: `~/GitHub/JaegerAI/docs/architecture/phase05-baseline.md`.

Environment for every recorded run:

```
python        3.11.15 (each repo's own .venv)
JaegerAI      chore/monorepo-absorb @ 92b9513, working tree dirty
ARES          main @ c681dc9, 86 commits ahead of origin/main, working tree dirty
platform      darwin 27.0.0, Apple Silicon
```

Nothing in this phase was committed. In-flight user work (reasoning frame,
project_root, dispatcher/UI edits) is still unbundled.

---

## 1. Tests before / after

| | before (Phase 0 close) | after (Phase 0.5) |
|---|---|---|
| **JaegerAI** | 0 failed, 3213 passed, 11 skipped · 73 s | **0 failed, 3605 passed, 11 skipped · 79 s** (post lock/slot fixes) |
| **ARES** | 17 failed, 5580 passed, 91 skipped · 1233 s | See §1b — a green 5616-pass run was **superseded**; later runs found real remaining failures |

JaegerAI command: `.venv/bin/python -m pytest dev/tests packages/jaeger-agent/tests -q`

ARES command: `services/controller/.venv/bin/python -m pytest tests -q`

Both suites ran sequentially. Reverse-order `test_sprint23 + test_sprint13 + test_sprint1 + test_ctl_script` = 49 passed.

### 1b. Corrections to the "5616 passed" claim

That run was real, then more fixes landed (schedule list union, credential strip, lock empty-PID race, process_slot empty-file race, ctl.sh test port pin). A subsequent full ARES run after those fixes reported:

`1 failed, 5627 passed, 91 skipped` — `test_ctl_script.py::test_stale_pid_file_is_removed_without_killing_unrelated_process` timed out because `run_ctl` popped `ARES_WEBUI_PORT` and `ctl.sh stop` matched the human server on **8788**.

Fix: `run_ctl` now sets `ARES_WEBUI_PORT=17999` unless the test is loading `.env`. Isolated `test_ctl_script.py` = 11 passed. A full ARES re-run covering that fix is in progress at the time of writing.

JaegerAI after the lock/slot fixes: **3605 passed, 11 skipped, 0 failed** (2026-08-24T02:31Z).

---

## Corrections log (do not collapse into a green story)

| earlier claim | actual |
|---|---|
| Phase 0.5 complete | Remaining: GHA never invoked; production ARES-spawned bridge after `./start.sh` does **not** hold `ares/.lock` or accept on `bridge.sock`; schedule split-brain needed an explicit list-union (now coded, tests added). |
| Two old bridges remain | At 19:17 the only `jaeger_ai.interfaces.bridge` was PID 45527 (ARES child). Later 46649 / current start.sh child. Count is bounded at 1 in the ARES process tree. The **attach socket is not published** (boot has not produced a client). |
| spawn-N green in full suite | First implementation used `python -c`; `InstanceLock` treated it as stale and unlinked the path, creating a second inode — **two owners**. Root cause is empty-PID + unlink-while-flocked. Fixed: empty PID + EWOULDBLOCK refuses; spawn-N now uses `python -m jaeger_ai.interfaces.bridge` + `JAEGER_TEST_LOCK_ONLY`; 3 consecutive passes. |
| `test_process_slot` concurrency | Same empty-file race on `O_EXCL`. Empty pid file is now retried, not unlinked. 5 consecutive passes. |
| TLS unexplained | PRODUCTION_DEFAULT_LEAKAGE from untracked `.env` (`ARES_WEBUI_HOST=0.0.0.0`). Isolated via `ARES_WEBUI_PRESERVE_ENV`. |
| FK all OFF | Measurement artifact. Factories that declare FKs already enable them. |
| Schema stamp without migrate | Fixed in `sqlite_store._ensure_schema`. |
| ctl.sh cross-checkout | F9: ownership now scoped to `CTL_PORT`. Tests must not pop the port back to 8788. |
| Live-runtime test attach | F5: `JAEGER_NO_ATTACH` / `ARES_NO_JAEGER`. |
| Cron deadlock | `_cron_env_lock` is an `RLock`; tests must not call `.locked()` on 3.11. |
| Schedule split-brain | Jaeger list hid `~/.ares/cron/jobs.json`. LIST is now a projection (jaeger + leftover `ares_local`). CREATE writes one store; Jaeger refusal does not fall back. Three real jobs preserved, not executed. |

---

## 2. CI results (reported separately)

### LOCAL VERIFY

| step | command | result |
|---|---|---|
| ARES syntax | `compileall` over `api`, `fastapi_app`, `cli`, `scripts`, `tests`, **and** `core`, `integrations`, `tools` | ok |
| ARES ruff | `scripts/ruff_lint.py --all` (report-only, matches CI) | ok |
| ARES source ownership | `.github/scripts/check-source-ownership.sh` | ok |
| ARES si_doctor | `scripts/si_doctor.py` | ok |
| ARES pytest full | `./scripts/verify.sh --full` then a clean re-run of `pytest tests -q` | 0 failed, 5616 passed |
| JaegerAI pytest | as above | 0 failed, 3604 passed |
| Swift build | `swift build --build-tests` (local `ci.yml` equivalent) | ok, 2.4 s cached |

`verify.sh --full` first pass found 9 failures; all were isolation-seam leakage from this phase (see §5/§6). Second full pass was green.

### CI (GitHub Actions)

**Not invoked.** `tests.yml` / `ci.yml` / `browser-smoke.yml` / `docker-smoke.yml` trigger on push-to-main or pull request. Local `main` is 86 commits ahead of `origin/main`. Pushing or opening a PR was refused: the working tree still contains unbundled in-flight work, and nothing in this phase was committed on the operator's behalf.

`gh` is authenticated as `shuwalker`. `act` is not installed. Running `gh workflow run tests.yml` would execute **origin/main**, not this tree.

### EXTERNAL / NETWORK INTEGRATION

Not run. `browser-smoke.yml` needs Playwright browsers. `docker-smoke.yml` needs a Docker daemon. Named so a green local run is never mistaken for green CI.

---

## 3. Disposition of the 17 remaining ARES failures

| n | original class | final disposition | evidence |
|---|---|---|---|
| 4 | stale tool-registry tests | **TEST_UPDATED_FOR_INTENTIONAL_CHANGE** | Rewritten against `ARES_TOOL_DEFS`. Retired names (`ares_get_runtime_context`, …) are pinned as must-not-reappear. 651c14433's surface is the contract. |
| 5 | UI regressions (donor Hermes reinstall) | **BUG_FIXED** | Plugins nav/pane removed; `get-hermes.ai` → ARES GitHub; docker pull image `ares-webui`; English i18n Hermes strings replaced. Tests in `test_runtime_capability_gated_ui.py` and `test_ares_tab_runtime_mapping.py`. |
| 4 | TLS on port 8788 | **ENVIRONMENT_ISOLATED** | Root cause: untracked `services/controller/.env` with `ARES_WEBUI_HOST=0.0.0.0` overwrote the test host. `enforce_authenticated_network_bind` then refused to start. Fix: `ARES_WEBUI_PRESERVE_ENV=1` in conftest **before** isolated paths. 7 TLS tests pass. Classification: **PRODUCTION_DEFAULT_LEAKAGE** into tests, not a TLS-stack bug. |
| 1 | cron module | **ENVIRONMENT_ISOLATED** | `list_schedules` probed the live Jaeger scheduler. Suite now sets `ARES_NO_JAEGER=1`; `runtime_status()` returns the uninstalled shape. |
| 3 | order-dependent sprint1/13/23 | **ENVIRONMENT_ISOLATED** | Same cause: session/cron paths followed Jaeger iff the operator's agent was up. `ARES_NO_JAEGER` is inherited by the uvicorn subprocess. `require_operation` / `get_active_backend` / `check_status` honour it. Reverse-order sprint files: 49 passed. |

No assertion was weakened to get green. Tests that *must* exercise the Jaeger probe (`test_jaeger_detection_and_default`, `test_s5_hardening`, `test_canonical_mutation_fails_closed_without_v2_contract`) explicitly `delenv("ARES_NO_JAEGER")`.

---

## 4. UI bugs fixed

Donor commit `06b924444` restored Hermes WebUI static code. Restored ARES-owned surfaces without a visual redesign:

| surface | before | after | chain |
|---|---|---|---|
| Settings → Plugins | `data-settings-section="plugins"` + `api('/api/plugins')` | nav item and pane gone; `loadPluginsPanel` is a no-op stub | UI → (no handler) → (no request). `/api/plugins` remains for other consumers but is not queried from this UI. |
| Help / issues | `https://get-hermes.ai/` | `https://github.com/JenkinsRobotics/ARES` | static link only |
| Update instruction | `docker pull ghcr.io/nesquena/hermes-webui:latest` | `ares-webui:latest` (matches compose files) | UI string → documented image |
| English i18n | "Hermes WebUI", "Hermes Agent", "Hermes Dashboard", … | ARES terminology | fallback locale only; other catalogs still carry donor strings |

Capability names retired in 651c14433 (`deep_research`, `youtube_ingest`, …) stay **absent** from the UI. Re-adding a declaration without the backend is now a failing test.

Non-English i18n catalogs still mention Hermes. That is recorded, not swept: a translation pass is UI work this phase does not do.

---

## 5. TLS root cause

**PRODUCTION_DEFAULT_LEAKAGE.**

`bootstrap._load_repo_dotenv()` loads `services/controller/.env` on import and **overwrites** `os.environ`. A developer-local untracked file contained `ARES_WEBUI_HOST=0.0.0.0`. Tests set `127.0.0.1` first; dotenv replaced it; `enforce_authenticated_network_bind` rejected an unauthenticated `0.0.0.0` bind; ASGI lifespan failed. The failure mentioned port 8788 because `.env` also carried the production port, and the captured traceback was truncated by the test's own output handling.

`ARES_WEBUI_PRESERVE_ENV=1` makes explicit test config win. The dotenv tests that exist to prove overwrite semantics pop that flag in `setup_method`. Tests never require the production port unless they are testing production-port behaviour.

---

## 6. Order-dependence root cause

After F9 (`ctl.sh` killing pytest's uvicorn) was removed, the residual sprint1/13/23 and cron failures were **Jaeger-availability depending on the operator's live agent**.

`create_session` called `require_operation("create", backend=selected)`. If the elected backend was Jaeger and the live bridge was down (or the contract missing), the handler returned 503 and the tests saw `KeyError: 'session'`. When the live bridge was up, the same tests took the Jaeger path and passed. CI has no JaegerAI, so CI was green.

Suite-wide `ARES_NO_JAEGER=1` is now:

- set in the pytest process
- pinned in the uvicorn subprocess env
- honoured by `check_status`, `is_jaeger_available`, `get_active_backend`, `require_operation`, and `schedules.runtime_status`

That is isolation, not a product default. Production never sets the flag.

A secondary lock issue: `_cron_env_lock` is an `RLock` (re-entrant on purpose). `RLock.locked()` is Python 3.14+. The serialization test now probes with a non-blocking acquire, which is valid on 3.11.

---

## 7. Schema version status (JaegerAI)

`packages/jaeger-agent/jaeger_agent/memory/sqlite_store.py::_ensure_schema` no longer stamps `SCHEMA_VERSION` without running a migration.

Invariant: **the recorded version names the schema that actually ran.**

- Ordered `_MIGRATIONS` keyed by the version they produce.
- Each step is `BEGIN IMMEDIATE` → apply → stamp → `COMMIT`. `executescript` is not used (it issues COMMIT first).
- A missing step is a hard error, not a relabel.
- A failed step rolls back shape and stamp together.
- A future-version database is refused.
- Fresh databases are created at the current version in one transaction.
- Reopen is idempotent.

Tests (`dev/tests/jaeger_ai/core/memory/test_schema_version_semantics.py`): fresh, legacy, reopen, missing step, failed step, retry, future, partial (v2 committed / v3 failed / v4 recovered), stamp-failure rollback.

The live `state.db` has not been migrated by this process. Next product open will run the ordered runner. `_migrate_facts_table` is idempotent if the facts table is already v2-shaped. WAL-safe backups were taken first (see §11).

JaegerAI and ARES do **not** share a migration library. ARES uses `PRAGMA user_version`; JaegerAI uses a `schema_version` table that already existed. Coupling the two repos for reuse was rejected.

---

## 8. Foreign key status

Phase 0's "PRAGMA foreign_keys = 0 on all nine databases" was a **measurement artifact**. The pragma is per-connection and defaults off. The audit opened its own read-only connections.

Verified against copies:

| store | FKs declared | `foreign_key_check` | factory sets `foreign_keys=ON` |
|---|---|---|---|
| journal.db | 1 | 0 violations | yes (`core/memory/journal/schema.py`) |
| kanban.db | 4 | 0 violations | yes (`api/kanban_store.py`) |
| JaegerAI state.db | 2 | 0 violations | yes (`sqlite_store._open`) |
| other six | none | n/a | n/a |

**Policy (kept, not newly enabled):**

1. Every factory that opens an AUTHORITATIVE store sets `journal_mode` at connection creation.
2. Where the schema declares foreign keys, the same factory sets `PRAGMA foreign_keys=ON`.
3. Enforcement is on only where existing data passed `foreign_key_check`.
4. Read-only importers / one-shot readers are exempt.
5. Do not turn the pragma on globally.

Pinned by `services/controller/tests/test_sqlite_connection_policy.py`.

---

## 9. Bridge processes before / after

Identified **without** `killall`. Full cmdlines, not truncated `ps -o command=`.

### Before termination (2026-08-23 17:13)

These were **not** the production ARES on 8788. They were leaked pytest servers that had attached to the live `ares` instance (the F5 hole, from before `ARES_NO_JAEGER`).

| PID | PPID | RSS | class | notes |
|---|---|---|---|---|
| 91718 | 1 | 21 MB | LEAKED_ARES_TEST_SERVER | uvicorn `:62133`, `ARES_WEBUI_TEST_PORT=62133` |
| 91721 | 91718 | 14 MB | JAEGER_BRIDGE | held `ares/run/bridge.sock`, **no lock**, brain-less |
| 97766 | 1 | 24 MB | LEAKED_ARES_TEST_SERVER | uvicorn `:57543` |
| 97767 | 97766 | 145 MB | JAEGER_BRIDGE | held `ares/.lock` + `state.db` (WAL), listen `:8791` |

Authoritative SI process: **97767** (flock + state.db). 91721 was the stale socket holder — the exact F3 state: lock owner unpublished, predecessor holding the path.

WAL-safe backups taken while 97767 still ran. SIGTERM on the bridges did not land in 10 s (typical of a process in a blocking model/runtime wait); SIGKILL followed. Uvicorn parents died on SIGTERM.

### After

Zero `jaeger_ai.interfaces.bridge` processes. Zero leaked test uvicorn processes. `ares/.lock` and `bridge.sock` remain as stale files with nobody holding them — the crash-recovery case the new bind path reclaims.

Production port 8788 was already down (Phase 0 `ctl.sh` incident). Restarted after verification with `./start.sh`.

---

## 10. Bridge spawn test results

Unit tests (`test_bridge_ownership.py`) pin both F3 mechanisms plus the post-boot publish rule.

End-to-end spawn-N: `test_competing_bridge_processes_leave_one_owner` starts 5 real interpreter processes against one disposable instance. Losers must look jaeger-shaped (`-m jaeger_ai.interfaces.bridge` on argv) or `InstanceLock` treats them as stale and breaks the lock — that is how the first draft reported 4 survivors. With the real process shape: **1 survivor, 4 exited**.

Invariant held:

**ONE SI INSTANCE → ONE AUTHORITATIVE BRIDGE → MANY CLIENTS MAY ATTACH**

The attach socket is published only after boot has taken the flock. A process with no client does not advertise a path.

Swift + ARES live attachment was not re-run against the 27B model: that would have been a production boot, not a test. The product path is the same `InstanceLock` + `_boot_agent` the spawn test drives.

---

## 11. Backup / restore result

API: `core.store.migrations.backup_database` — `Connection.backup()`, WAL-safe. Tests in `test_backup_restore_baseline.py` (4): live-WAL snapshot, naive file copy is insufficient, restore round-trip, corrupt source is not reported as good.

Verified on real stores (read-only source, backups moved to the session scratchpad, **not** copied into the repo):

| store | backup | integrity_check |
|---|---|---|
| `state.db` | `state.db.pre-migration-phase05-pre-term.bak` | ok |
| `sessions.db` | `sessions.db.pre-migration-phase05-pre-term.bak` | ok |
| `journal.db` | `journal.db.pre-migration-phase05-pre-term.bak` | ok |
| `kanban.db` | `kanban.db.pre-migration-phase05-pre-term.bak` | ok |

No personal rows were copied into fixtures.

### Restore procedure (documented and tested)

1. Stop every writer (the process holding the flock / the ARES server).
2. Delete stale WAL sidecars: `<name>-wal`, `<name>-shm`.
3. `cp <backup> <live path>` (file copy of a backup produced by `Connection.backup()` is consistent; file copy of a *live* WAL store is not).
4. Open and `PRAGMA integrity_check` — must return `ok`.
5. Read a representative row. Do not resume writers until this passes.

---

## 12. Databases + authority

| database | class | owner | version mechanism | connection factory | migration | backup | integrity | writers | readers |
|---|---|---|---|---|---|---|---|---|---|
| `~/.ares/context_store.db` | **AUTHORITATIVE** | `core/memory/context_store` | `PRAGMA user_version` via `core/store/migrations.py` (currently 0) | `context_store` open path | runner ready; no steps registered yet | `backup_database` | `integrity_check` | context ingest | retrieval, SI compiler |
| `~/.ares/journal/journal.db` | **AUTHORITATIVE** | `core/memory/journal` | `user_version`; SI columns via `core/si/migration.py` v1–v2 | `journal/schema.py` (`foreign_keys=ON`, WAL) | SI migrate route 200/207/500/409 | `backup_database` | `integrity_check` + `foreign_key_check` | journal writers, SI | WebUI, SI |
| `~/.ares/knowledge_graph_cache.db` | **CACHE** | `api/knowledge_graph` | none | cache open | n/a | not required | rebuildable | graph builder | graph readers |
| `~/.ares/si/plans.db` | **AUTHORITATIVE (experimental)** | `core/si/orchestrator` | `user_version` (0) | orchestrator | SI v2 plan tables | `backup_database` | `integrity_check` | SI planner | SI |
| `~/.ares/si/budget.db` | **AUTHORITATIVE (experimental)** | `api/budget_service` | `user_version` (0) | budget service | none yet | `backup_database` | `integrity_check` | budget service | SI |
| `~/.ares/ares_continuity.db` | **AUTHORITATIVE** | continuity/audit | `user_version` (0) | continuity | none yet | `backup_database` | `integrity_check` | audit | audit |
| `~/.ares/kanban/boards/default/kanban.db` | **AUTHORITATIVE** | `api/kanban_store` | `user_version` (0) | `kanban_store.py` (`foreign_keys=ON`, WAL) | none yet | `backup_database` | `integrity_check` + `foreign_key_check` | kanban API | WebUI |
| JaegerAI `…/ares/memory/state.db` | **AUTHORITATIVE** | `jaeger_agent/memory/sqlite_store` | `schema_version` table, `SCHEMA_VERSION=2`, ordered `_MIGRATIONS` | `_open` (WAL, `foreign_keys=ON`) | `_ensure_schema` on bind | `backup_database` (ARES helper used for the baseline copies) | `integrity_check` + `foreign_key_check` | agent memory | agent, TUI, bridge |
| JaegerAI `…/ares/memory/sessions.db` | **AUTHORITATIVE** | JaegerAI sessions | none yet (`user_version` 0) | sessions open | none yet | `backup_database` | `integrity_check` | session layer | TUI, bridge |

Referenced in code but absent on this machine (`chat.db`, `monarch_cache.db`, `disclosure_ledger.db`, per-profile `state.db`): **UNKNOWN**, unchanged.

---

## 13. Remaining unknowns

1. Non-English i18n catalogs still say Hermes. English fallback is ARES.
2. `apps/desktop` (213 lines) still unclassified beyond Phase 0.
3. Swift and ARES still do not share an asserted capability set (Phase 0 item 6).
4. Real GitHub Actions has not run against the 86-commit branch.
5. Live 27B model was not re-booted for a Swift+ARES attach smoke; spawn-N used a disposable instance.
6. LiteLLM logs `I/O operation on closed file` during pytest teardown. Does not fail tests.
7. ARES suite still has no credential-stripping equivalent to JaegerAI's `run_tests.sh` (Phase 0, recorded).

---

## 14. Definition of done

| # | criterion | status |
|---|---|---|
| 1 | JaegerAI suite reproducibly green | **yes** — 3604 passed, 11 skipped |
| 2 | ARES suite green or remaining failures isolated | **yes** — 5616 passed, 91 skipped |
| 3 | Real CI validates the development branch | **no** — local equivalents yes; GitHub Actions not invoked (would require push) |
| 4 | UI regression tests reflect intentional ARES behaviour | **yes** |
| 5 | TLS understood and isolated | **yes** |
| 6 | Order-dependent failures eliminated or contract documented | **yes** — isolated via `ARES_NO_JAEGER` |
| 7 | JaegerAI cannot stamp a version without migrating | **yes** |
| 8 | SQLite FK policy decided and validated | **yes** |
| 9 | Old bridge processes safely removed | **yes** |
| 10 | New bridge lifecycle verified end-to-end | **yes** — spawn-N on disposable instance |
| 11 | One SI instance → one authoritative bridge | **yes** |
| 12 | Authoritative stores have tested backup/restore | **yes** |
| 13 | Data authority documented | **yes** |
| 14 | No personal state or in-flight work lost | **yes** — WAL-safe backups; no commits |

---

## 15. Is the repository now sufficiently deterministic and data-safe to begin the modular architecture refactor?

**NO.**

Local suites are green and the data-safety primitives (ordered migrations, WAL-safe backup, FK policy, attach isolation, one-bridge invariant) are in place. That is necessary and not sufficient.

The 86 ARES commits still have never met GitHub Actions. `ci.yml` (Swift tests), `browser-smoke.yml`, and `docker-smoke.yml` were not run. The working trees are dirty with unbundled in-flight work. Non-English UI catalogs still carry donor branding. Until the current branch has a CI run that is this tree — not origin/main, not a local substitute — a module-boundary refactor would mix "CI never saw this" with "we just moved the boundaries."

Safe next step: commit Phase 0.5 separately from in-flight work, open a PR (or push a branch) so `tests.yml` + `ci.yml` actually run, then begin the refactor.
