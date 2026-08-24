# Phase 0 — Stabilization, Test Isolation, Process Lifecycle, Data Safety

Spans both repositories: `~/GitHub/ARES` and `~/GitHub/JaegerAI`.
Started 2026-08-23. Baselines below were captured on that date.

The objective is not new capability. It is a substrate on which a regression can
be told apart from a pre-existing failure, a test from production, a client from
a runtime, and a current schema from a historical one.

---

## Baseline

Captured with the two suites run **sequentially**, never concurrently.

| | command | result | duration |
|---|---|---|---|
| **JaegerAI** before | `.venv/bin/python -m pytest dev/tests -q` | 2 failed, 3201 passed, 11 skipped | 209 s |
| **JaegerAI** after | same | **0 failed, 3213 passed, 11 skipped** | **73 s** |
| **ARES** before | `.venv/bin/python -m pytest tests -q` | 272 failed, 5292 passed, 91 skipped, 3 xfailed, 13 errors | 472 s |
| **ARES** after | same | **17 failed, 5580 passed, 91 skipped, 1 xfailed, 2 xpassed** | 1233 s |

Environment for every run:

```
python        3.11.15 (both repos, each repo's own .venv)
JaegerAI      chore/monorepo-absorb @ 92b9513, working tree dirty (in-flight user work)
ARES          main @ c681dc9, working tree dirty (in-flight user work)
platform      darwin 27.0.0, Apple Silicon
```

The JaegerAI runtime drop from 209 s to 74 s is not an optimisation. It is the
suite no longer waiting on round trips to the operator's real agent (F5).

---

## F5 — Tests attached to the live runtime

**Root cause.** `create_runtime()` calls `try_attach_runtime()` *before*
`JaegerAIRuntime(...)`. On any machine with a live agent, `AgentCore.__init__`
reached the attach path, so a test that did
`monkeypatch.setattr(m, "boot_for_tui", fake)` never got to its own patch — it
proxied real turns to the operator's real brain, against real memory and real
credentials. CI has no live socket, so CI stayed green and only the developer's
machine went red. The two visible failures were the smaller half of the problem.

**Change.** A single choke point, gated by explicit configuration rather than
by monkeypatch timing:

- `jaeger_ai/core/runtime/attach_policy.py` *(new)* — `JAEGER_NO_ATTACH`, read
  by `attach_disabled()`. Mirrors the existing `JAEGER_NO_GUI` idiom, which the
  same conftest already sets for the same class of reason.
- `jaeger_ai/core/runtime/attached.py` — `try_attach_runtime()` consults the
  policy first. It is **the** choke point: every attach (`create_runtime`, the
  windowed app, anything added later) passes through it, so a new caller cannot
  reopen the hole by forgetting to ask.
- `dev/tests/conftest.py` — sets the gate suite-wide; adds
  `bindable_instance_root` (a short `/tmp` root — AF_UNIX paths cap near 104
  bytes and pytest's `tmp_path` exceeds it) and `allow_bridge_attach`, which
  lifts the gate **only after** pinning `JAEGER_INSTANCE_DIR` to a disposable
  root and refusing if that root is inside a live instance tree.
- `dev/scripts/run_tests.sh` — exports the gate too, because it is the
  documented entry point and gets used long before anyone reads the conftest.

**Why an environment gate and not a parameter.** Attachment is decided several
frames below every caller that would have to thread a flag through
(`AgentCore` → `create_runtime` → `try_attach_runtime`), and a caller that
forgets the flag gets the *dangerous* default. A process-wide gate fails the
other way: the suite is isolated even on paths nobody audited.

**Tests proving the fix** — `dev/tests/jaeger_ai/core/test_attach_isolation.py`,
which encodes the three-part requirement literally: a live bridge is stood up
(a real bound socket, not a mock), the suite runs, and nothing attaches to it.
A fourth test lifts the gate and asserts attachment *does* happen, so a refactor
that broke socket discovery entirely cannot leave the others passing vacuously.

**Files changed**

```
jaeger_ai/core/runtime/attach_policy.py            (new)
jaeger_ai/core/runtime/attached.py
dev/tests/conftest.py
dev/scripts/run_tests.sh
dev/tests/jaeger_ai/core/test_attach_isolation.py  (new)
dev/tests/jaeger_ai/core/test_attached_runtime.py  (rewritten onto the fixture)
```

---

## F3 — Bridge process leak and startup storm

**Root cause.** Two behaviours that fed each other. Established by reading the
lifecycle end to end; both halves are in `jaeger_ai/interfaces/bridge.py`.

1. **A bridge that lost the instance flock stayed alive.** `_boot_agent`
   caught the lock error, emitted `fatal(kind="locked")`, and *returned*. The
   transport kept serving, so a process with no agent and no prospect of one
   sat at ~75 MB indefinitely, waiting for a stdin EOF that may never arrive.

2. **That same process had already hijacked the owner's attach socket.**
   `_start_bridge_socket` was called unconditionally, and `bsock.bind()`
   unlinks whatever file is in its way — correct for a *stale* socket left by a
   crash, catastrophic for a *live* one. Every client that attached afterwards
   reached the brain-less bridge, gave up, and spawned another, which lost the
   lock and hijacked the socket in turn.

Together those are the orphan pile and the 45-second spawn burst in one
mechanism. Observed evidence at discovery: 18 bridge processes, 12 reparented
to PID 1, 14 spawned inside 45 seconds, ~1.3 GB combined RSS.

**Invariant now enforced:** one instance → at most one authoritative bridge
runtime. Many clients may attach; none of them creates a second long-lived
bridge.

**Change.**

- `_Ctx` gains `exit_requested` and `inbound`, so the boot thread — which
  discovers the lock loss — can reach a main loop it does not otherwise see.
- `_request_exit()` sets the event *and* pushes the shutdown sentinel. The boot
  thread starts before `inbound` exists, so the event covers the early case and
  `main` re-checks it the moment the queue is created.
- `_boot_agent` treats lock loss as terminal: emit the fatal frame (the client
  needs it in order to go attach to the real owner), then leave. Every *other*
  boot failure still keeps the transport alive — a model that fails to load is
  a degraded agent, not a duplicate one, and the native app's first-run flow
  runs on that transport.
- `_start_bridge_socket` probes before binding. A path that accepts a
  connection belongs to somebody; a path that does not is stale and is still
  reclaimed, so crash recovery keeps working.

**Tests** — `dev/tests/jaeger_ai/core/test_bridge_ownership.py` (6):
no hijack of a live socket; stale sockets still reclaimed; competing binds
produce exactly one owner; lock loss requests exit; an ordinary boot failure
does *not*; the exit request survives arriving before the queue exists.

They drive the real socket helpers rather than mocks — the whole bug lived in
what `bind` does to a file that already exists, and a mock would have modelled
the intent instead of the behaviour.

**Files changed:** `jaeger_ai/interfaces/bridge.py`,
`dev/tests/jaeger_ai/core/test_bridge_ownership.py` *(new)*.

**Risk.** The probe adds a ≤0.4 s connect attempt to bridge startup. The
`exit_requested` path is new control flow on a failure branch; the
`test_an_ordinary_boot_failure_keeps_the_transport_alive` test exists
specifically to stop it widening.

---

## F9 — Test nondeterminism: **finding revised**

> **The original F9 was wrong and is superseded.** It attributed the
> 272-vs-15 failure swing to concurrent suite execution. That was a correlation
> — the two runs did overlap — and it did not survive investigation.

**What actually happens.** `ctl.sh`'s `_is_owned_webui_pid` accepted *any*
process whose command line contained both `uvicorn` and `fastapi_app.main:app`:

```bash
( "${args_slash}" == *"uvicorn"* && "${args_slash}" == *"fastapi_app.main:app"* )
```

No repo root, no state directory, no `HOME`, no port. The pytest session's own
isolated test server is launched as
`python -m uvicorn fastapi_app.main:app --host 127.0.0.1 --port <free port>`,
so `ctl.sh stop` — reached through `test_ctl_script.py` — matched it, judged it
"ours", and SIGTERMed it. Every later HTTP test in the session then failed with
`URLError`. Whether a run reported 15 failures or 272 depended on collection
order: on *when* the ctl test ran relative to the HTTP-dependent ones.

**Controlled experiment.**

| run | result |
|---|---|
| `pytest tests/test_sprint7.py` | 19 passed |
| `pytest tests/test_ctl_script.py tests/test_sprint7.py` | 20 failed, 10 passed |
| same pair, after the fix | **30 passed** |

**This is also a production bug, not only a test artifact.** Two ARES checkouts
on one machine (a worktree and the main clone) would stop each other's servers,
because the ownership test ignored which install a process belonged to.

**Change.** `services/controller/ctl.sh` — the uvicorn branch is scoped to this
install. An explicit `--port` must equal `CTL_PORT`; with no `--port`, the
process must genuinely be listening on `CTL_PORT` (verified via `lsof`).
Unattributable is treated as **not ours**: this is the last-resort branch, and
declining to stop is better than killing a stranger. `ctl.sh` never launches
uvicorn itself (it goes through `bootstrap.py` / `start.sh`), so this clause
only ever recognised a hand-started server — for which the port is the only
meaningful discriminator.

**Tests** — `test_ctl_script.py::test_stale_pid_file_is_removed_without_killing_unrelated_process`
(was failing, now passes) plus a source-level pin in
`tests/test_phase0_boundaries.py`.

---

## F4 — Persistent stores had no versioning

### Inventory

Read-only inspection of every SQLite store on this machine.

| database | owner | size | tables | `user_version` | journal | FK enforced | class |
|---|---|---|---|---|---|---|---|
| `~/.ares/context_store.db` | `core/memory/context_store` | **1.06 GB** | 7 (238 340 chunks, 28 119 sources, sqlite-vec) | 0 | WAL | no | AUTHORITATIVE |
| `~/.ares/journal/journal.db` | `core/memory/journal` | **296 MB** | 18 (28 174 documents + FTS5) | 0 | WAL | no | AUTHORITATIVE |
| `~/.ares/knowledge_graph_cache.db` | `api/knowledge_graph` | 5.0 MB | 1 (8 711 rows) | 0 | WAL | no | CACHE |
| `~/.ares/si/plans.db` | `core/si/orchestrator` | 28 KB | 1 (18 plans) | 0 | delete | no | AUTHORITATIVE (experimental) |
| `~/.ares/si/budget.db` | `api/budget_service` | 20 KB | 2 (empty) | 0 | delete | no | AUTHORITATIVE (experimental) |
| `~/.ares/ares_continuity.db` | continuity/audit | 28 KB | 3 | 0 | delete | no | AUTHORITATIVE |
| `~/.ares/kanban/boards/default/kanban.db` | `api/kanban_store` | 52 KB | 5 (empty, 4 FKs declared) | 0 | WAL | no | AUTHORITATIVE |
| `JaegerAI .jaeger_ai/instances/ares/memory/state.db` | `jaeger_agent/memory/sqlite_store` | 6.7 MB | 9 (518 episodic, 1 564 tool calls) | 0 | WAL | no | AUTHORITATIVE |
| `…/memory/sessions.db` | JaegerAI sessions | 400 KB | — | 0 | WAL | no | AUTHORITATIVE |

Referenced in code but not present on this machine: `state.db` (195 call sites —
per-profile), `chat.db`, `monarch_cache.db`, `disclosure_ledger.db`,
`context_store.db` variants. Those remain **UNKNOWN** pending a profile-populated
machine.

Two observations that outlive this table:

- **`PRAGMA foreign_keys` is 0 on every database.** FK constraints are declared
  (kanban 4, journal `messages` 1, JaegerAI `episodic`/`tool_calls`) and **not
  enforced** — the pragma is per-connection and defaults off. Recorded, not
  changed: switching it on retroactively can fail against rows that already
  violate it, which is its own migration.
- **JaegerAI already had a versioning mechanism** (`schema_version` table in
  `sqlite_store.py`) and ARES had none. But JaegerAI's "older version → future
  migration runner" branch *stamps the new version without running anything*,
  so a v1 database opened by v2 code is marked migrated without being migrated.
  Recorded as an open item; not changed in Phase 0.

### The migration foundation

`core/store/migrations.py` *(new)* — a lightweight internal runner. No new
dependency: Alembic is built around a single application database with an
autogenerate workflow against declarative models; this is nine heterogeneous
stores, several with hand-rolled schemas and virtual tables (FTS5, sqlite-vec)
that autogenerate cannot see. The runner is ~200 lines and does exactly what is
needed.

Design decisions and the alternative each rejects:

- **`PRAGMA user_version`, not a version table.** It is a header field written
  inside the same transaction as the DDL it describes, so version and shape can
  never disagree. It also costs nothing on existing databases — they already
  read 0, which is exactly "before migration 1". A version *table* needs its own
  CREATE before it can be read, which is a migration problem of its own.
- **One transaction per migration, not one for all.** SQLite DDL is
  transactional, so a failure rolls back to the version boundary before it. This
  is what makes `PARTIAL_FAILURE` an honest, recoverable state: everything below
  the reported version is committed, the failing step is fully undone, and a
  re-run resumes there.
- **`BEGIN IMMEDIATE`.** Takes the write lock up front, so a concurrent writer
  fails before any DDL rather than halfway through.
- **Refuse a database from the future.** Writing an old shape over a newer one
  is unrecoverable; refusing is not.
- **Back up before destructive steps, via `Connection.backup()`.** These stores
  run WAL; copying the main file with `shutil` loses whatever is still in the
  `-wal`, producing a backup silently behind the original. A failed backup
  **aborts** the migration — a destructive step with no recovery copy is exactly
  what this module exists to prevent.

**Tests** — `services/controller/tests/test_store_migrations.py` (13), built on
fixtures shaped like the databases actually on disk (real columns, real rows,
`user_version` 0) rather than mocked version numbers. They assert what the
database looks like *after* something goes wrong: failure on step 1 leaves it
byte-identical; failure on step 3 leaves it coherent at v2; DDL executed before
a mid-migration failure does not survive; WAL backups are consistent.

---

## F4b / §11 — A failed migration could not report failure

`POST /api/si/migrate` called a function that caught every per-column
exception, wrote `f"error: {e}"` into a dict, and returned it with **HTTP 200**.
Nothing called it at startup either, so the SI columns existed only if an
operator remembered to POST.

**Change.**

- `core/si/migration.py` — rebuilt on the runner as two ordered migrations
  (`v1 si-sensitivity-columns`, `v2 si-plan-tables`). Missing *optional* tables
  (`documents`, `messages` — created lazily by the journal's own open path) are
  **skipped and recorded**, not failed; the distinction between "nothing to do"
  and "could not do it" is the entire point. `ADD COLUMN` is checked against
  `PRAGMA table_info` rather than caught as a duplicate-column error, so a
  genuine failure still propagates. The legacy `migrate_journal_sensitivity`
  dict shape is preserved for existing callers, now derived from a real report.
- `fastapi_app/routers/si.py` — status codes carry the outcome:
  `200` SUCCESS · `207` PARTIAL_FAILURE · `500` FAILED · `409` database written
  by a newer ARES. Full report in the body either way; failures are logged.

---

## F2 — Classification of the remaining deterministic failures

After the `ctl.sh` fix removed 255 cascading failures, **17 remain**. Every one
is classified from product/runtime evidence. **No assertion was weakened.**

### INTENTIONAL_BEHAVIOR_CHANGE → the tests are stale (4)

`test_ares_tool_adapter.py` — `TestAresTools` (3) and `TestToolAdapter::test_stdio_mcp_dispatches_canonical_ares_tool` (1).

Commit `651c14433 feat(modes): cognitive operating modes, ARES tools, and repo map`
deliberately **replaced the entire ARES tool surface** (−307/+168 lines):

| removed | added |
|---|---|
| `ares_get_runtime_context`, `ares_create_task`, `ares_update_task`, `ares_extract_pdf`, `ares_fill_pdf_form`, `ares_ingest_youtube`, `ares_edit_image`, `ares_create_visual_report`, `ares_list_artifacts`, `ares_start_research`, `ares_get_research` | `ares_add_workspace`, `ares_list_workspaces`, `ares_set_mode`, `ares_get_mode`, `ares_trigger_dream`, `ares_write_memory_note`, `ares_get_repo_map`, `ares_run_verification` |

The commit message even acknowledges one *other* test it breaks. The tests
still describe the retired surface. **Correct fix: rewrite the tests against
the new registry — never re-add the removed tools.** Not done here: it is a
product decision about which tool surface is intended, and Phase 0 does not
make product decisions. Left failing and documented.

### BUG — regression from a bulk static-code reinstall (5)

`test_runtime_capability_gated_ui.py` (3) and `test_ares_tab_runtime_mapping.py` (2).

`06b924444 feat(webui): fresh reinstall of WebUI static code from donor Hermes app`
overwrote `apps/web/static/` wholesale, **undoing** the de-Hermesification that
`776771e5f feat: enforce capability-owned UI domains` and
`12d664e51 fix: align ARES tabs with Jaeger runtime ownership` had established.
It re-introduced `data-settings-section="plugins"` and `https://get-hermes.ai/`
links, and dropped the `data-requires-capability` annotations and the
`openExternalDashboard` handler.

On the question of whether the UI is premature, the test stale, or a capability
boundary being violated — the evidence says **the tests are right and the UI
regressed**. The tests were written *after* the surfaces they ban, specifically
to keep them out; a later bulk import brought them back.

One nuance worth recording, because it changes the severity: the capability
names the gating test expects (`deep_research`, `youtube_ingest`, `pdf_forms`,
`image_gallery`, `image_editor`, `visual_reports`) now have **zero** references
anywhere in the web UI. So the retired tools and their panels went away
together — this is not a UI advertising capabilities the backend lost. What
remains is the legacy *plugins* settings surface and Hermes branding.

Fixing this properly means restoring ARES's capability-gating layer in the
static UI, which is UI work §16 explicitly defers. **Left failing and
documented as an accepted, understood failure.**

### ENVIRONMENT / UNKNOWN (5)

`test_tls_support.py` (4) — the test's own bootstrap server fails at ASGI
  lifespan startup, on the **production port 8788**, with
  `TLS setup failed ([Errno 2] No such file or directory)` in one variant. The
  captured traceback is truncated by the test's own output handling, so the
  underlying exception was not recovered. **UNKNOWN**, leaning environment;
  not forced to an answer.

`test_issue4768_cron_module_missing.py::test_list_schedules_uses_internal_schedule_module`
— asserts a schedule's module is `"internal"`; it reads back a description
string instead. Adjacent to the cron/schedule rework in the unpushed commits.
**UNKNOWN**.

### Order-dependent within the suite (3)

`test_sprint1.py::test_session_delete_removes_attachment_inbox`,
`test_sprint13.py::test_workspace_add_accepts_real_dir` (`KeyError: 'session'`)
and `test_sprint23.py::test_cron_create_accepts_skills`. Each passes in
isolation and the *set* shifts between runs — the residual nondeterminism after
the `ctl.sh` fix removed the dominant cause. **UNKNOWN**; the next concurrency
pass should start here.

### Fixed by the ctl.sh change

`test_ctl_script.py::test_stale_pid_file_is_removed_without_killing_unrelated_process`
was failing at baseline and now passes. It remains sensitive to a real server
occupying port 8788: the test pops `ARES_WEBUI_PORT`, so `ctl.sh` falls back to
the production default and legitimately stops whatever is listening there,
exceeding the test's 5 s timeout. Pinning a test port is a one-line hardening,
left out to keep the `ctl.sh` change reviewable on its own.

---

## F6 — Authoritative code outside the syntax gate

`tests.yml` sets `working-directory: services/controller` under a comment
reading "The ARES web app lives entirely under `services/controller/`". True
before the `core/` extraction; now false by ~18 000 lines.

Precisely: the **ruff diff gate covers** `core/` and `integrations/` (it resolves
changed files against the git root); **`compileall` does not** (its argument list
stops at `services/controller`); **pytest covers `core/` indirectly** through the
`api/` shims. Addressed in `scripts/verify.sh` below; the workflow itself is
left alone so the CI change can be reviewed on its own.

---

## F1 — 86 commits that never met a gate

Local `main` is 86 commits ahead of `origin/main` and 20 behind. Every ARES
workflow triggers on push-to-main or on a pull request; none of those commits
did either. The gates were never weak — they were never invoked. This is the
root cause of F2: the failures were merged because nothing ran.

**No git history was altered.**

**Change.** `scripts/verify.sh` *(new)* — the local equivalent of CI.

```
./scripts/verify.sh          fast gate: syntax, ruff, architecture, si_doctor, unit tests
./scripts/verify.sh --full   adds the complete ~5 600-test suite
./scripts/verify.sh --list   prints what each mode runs
```

No credentials, no network, no Docker on the default path. Its `compileall` step
covers `core`, `integrations` and `tools` — the gap F6 identified. It
deliberately does **not** claim to be a superset of CI: browser-smoke needs
Playwright, docker-smoke needs a daemon, `ci.yml` needs Xcode. All three are
named in the output so a green local run is never mistaken for a green CI.

JaegerAI already has the equivalent (`dev/scripts/run_tests.sh`), which pins
`TZ`/`LANG`/`PYTHONHASHSEED` and strips every credential-shaped environment
variable. It needed only the attach gate added.

---

## §15 — Architecture fitness tests

`services/controller/tests/test_phase0_boundaries.py` *(new)*. Minimum set —
each pins a property a finding showed was **not** holding:

1. ARES imports no `jaeger_ai` / `jaeger_os` / `jaeger_agent` module (AST walk
   over `core`, `integrations`, `api`, `fastapi_app`). The bridge protocol is
   the boundary; Python imports are not.
2. `core/si` stays opt-in while disabled — plus its mirror, that enabling it
   works, so a broken `si_enabled` cannot satisfy the first.
3. `ctl.sh`'s ownership branch stays scoped to `CTL_PORT`.
4. The migration runner is importable and its three outcomes stay distinct.
5. No store reports failure as an `"error: ..."` string inside an otherwise
   successful result.

---

## Security (§14)

- Tests can no longer reach the live runtime, live sockets, or the operator's
  instance state (F5). `allow_bridge_attach` refuses to run if its root
  resolves inside a live instance tree.
- `dev/scripts/run_tests.sh` already strips every `*_API_KEY` / `*_TOKEN` /
  `*_SECRET` / `*_PASSWORD` plus the AWS/GitHub canonicals.
- ARES's test server already runs on an OS-assigned free port with a
  per-process state directory.
- **No user data was copied into any fixture.** Every test fixture is
  synthetic. The database inventory was gathered with read-only connections
  (`file:…?mode=ro`); no store was opened for writing.
- Still open: ARES's suite has no credential-stripping equivalent to
  JaegerAI's. Recorded, not addressed.

---

## Open items — carried forward

| # | question | confidence | disposition |
|---|---|---|---|
| 1 | Do the four ARES UI surfaces converge or coexist? | UNKNOWN | Behaviour preserved. `apps/web` is the only one with UI-contract tests and a smoke job. |
| 2 | Is `apps/desktop` (213 lines) a stub? | LOW | Behaviour preserved. |
| 3 | Is `core/si` intended to become the default turn path? | MEDIUM — default-off is explicit and commented "until production enables SI via launchd or settings"; **no `si_enabled` key exists in this operator's `~/.ares/settings.json`, so SI is OFF here** | Pinned as opt-in by test; not enabled. |
| 4 | What spawns the bridge burst? | **HIGH — resolved.** Lock-loser lingering + socket hijack, see F3. | Fixed. Bounded-count verification pending a reproduction run. |
| 5 | Are the four `test_tls_support` failures environmental? | **HIGH — resolved in Phase 0.5.** Untracked `.env` overwrote the test host. Isolated via `ARES_WEBUI_PRESERVE_ENV`. | See `phase05-baseline.md`. |
| 6 | Do Swift and ARES agree on the bridge capability set? | UNKNOWN | `protocol_v1_fixtures.json` pins frame shapes; nothing asserts the two clients consume the same `CAPABILITIES`. Not addressed. |
| 7 | JaegerAI's `sqlite_store` version bump without migration | **HIGH — resolved in Phase 0.5.** Ordered `_MIGRATIONS`; stamp and DDL share a transaction. | See `phase05-baseline.md`. |
| 8 | `PRAGMA foreign_keys` off on all nine stores | **HIGH — corrected in Phase 0.5.** Measurement artifact (pragma is per-connection). Factories that declare FKs already enable them; live data has zero `foreign_key_check` violations. | See `phase05-baseline.md`. |

---

## Not started (§16 — deliberately)

Cognitive world model, claim/evidence/belief, memory redesign, plugin overhaul,
planner architecture, multi-agent redesign, self-improvement, large module
moves, global renaming, UI redesign, graph database.

---

## Incident during this work

While timing `ctl.sh stop` by hand to diagnose the test timeout above, the
command found and stopped the ARES web server that was listening on port 8788
(PID 71504). `HOME` was faked for the invocation but `CTL_PORT` fell back to
the production default, so the port-owner lookup correctly identified the real
server and stopped it. A headless Chrome pointed at `127.0.0.1:8788` was left
running. `ARES.app` was already not running beforehand.

Nothing was lost — this is a clean stop, not data loss — but the server was not
restarted, because restarting a daemon is the operator's call. Restart with:

```
cd ~/GitHub/ARES && ./start.sh          # or: bin/ares start --server
```

The underlying lesson is the same one F9 records: a `stop` verb that resolves
its target from a machine-wide default port is easy to fire at the wrong thing.

---

## In-flight user work — untouched

The JaegerAI branch carries uncommitted work on the reasoning frame,
`project_root` binding, and dependency de-duplication across 33 files. **None of
it was modified, reverted, or bundled with Phase 0.** Every Phase 0 change is in
a disjoint file except `jaeger_ai/interfaces/bridge.py`, where the in-flight
edits touch `_delta_frame`/`_turn_workspace`/`_turn_worker` and the Phase 0
edits touch `_Ctx`/`_boot_agent`/`_start_bridge_socket`/`main` — non-overlapping
regions. Nothing was committed on the user's behalf.
