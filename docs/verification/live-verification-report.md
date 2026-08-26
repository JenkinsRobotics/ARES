# ARES ↔ Jaeger live verification

Date: 2026-08-25/26. Evidence was produced from the dirty working trees and was not inferred from comments or documentation.

## Verdict

The three previously missing boundaries were executed successfully:

1. **Real model decode and multi-turn memory:** `qwen3.5:397b` returned `ACK`, then exactly recalled `codeword-5cc13ab4` and `fact-1d9bd1bc` on turns 2 and 3. A separate saved-session resume exactly recalled `token-d8aecf22`.
2. **Physical bridge replacement:** the harness resolved the listening socket to PID **29754**, verified its PPID, command, instance `ares`, and exact socket, signalled that PID, and observed replacement PID **29986**. The replacement exactly recalled the pre-death token `death-dc6f861a` and exposed 11 MCP tools.
3. **Live read-only Mail:** the agent emitted real `tool.running` and `tool.completed` events for `list_mailboxes` before and after replacement. Only account names and mailbox counts were requested; no subjects, bodies, sends, moves, or deletions were performed.

This proves those named boundaries. It does **not** prove every feature of ARES or JaegerAI works.

## Defect found and fixed during verification

Closing a client attached to an existing bridge could deadlock or raise in its reader thread. `JaegerClient.close()` now shuts down the socket first, waits briefly for the reader to exit, then closes the file/socket handles. The former strict-xfail lifecycle test is now an ordinary passing test.

Verification of the fix:

```text
tests/test_jaeger_client_lifecycle.py + tests/test_validate_live_verification.py
12 passed in 8.60s
```

The broader production-object suite recorded by the live harness also passed.

## Exact live observations

| Boundary | Expected | Actual | Result |
|---|---|---|---|
| Gateway routing | Real backend selects streaming gateway | `is_gateway=true`, `is_jaeger=true`, exact worker object | Pass |
| Turn 1 | Store unique facts | `ACK` | Pass |
| Turn 2 | Recall codeword | `codeword-5cc13ab4` | Pass |
| Turn 3 | Recall second fact | `fact-1d9bd1bc` | Pass |
| Explicit resume | Recall saved token | `token-d8aecf22` | Pass |
| Mail before death | Captured named tool events | `list_mailboxes` running + completed | Pass |
| Physical replacement | Different verified listener PID | `29754 → 29986` | Pass |
| Recall after death | Exact pre-death token | `death-dc6f861a` | Pass |
| Tools after death | Non-empty live inventory | 11 MCP tools | Pass |
| Mail after death | Captured named tool events | `list_mailboxes` running + completed | Pass |
| Attached-client shutdown | No deadlock/unhandled reader exception | Lifecycle regression test passes | Pass |
| Current installed status | ARES.app reports a live model | `connected`, `qwen3.5:397b`, available | Pass, but see deployment caveat |

## Honesty boundaries

- The strict 32-phase validator is still red because cancellation, steering, clarification, approval allow/deny, secret redaction, concurrency, disconnect, repeated lifecycle cycles, and loaded-revision proof were not executed live. They are not silently marked as passes.
- The installed ARES.app process runs with cwd `/Users/matthewjenkins/GitHub/ARES/services/controller` and currently reports the live model, but it started before the latest dirty-tree edits. Therefore it is not proof that the running app loaded the new close fix; an app restart is still required for that claim.
- The non-idempotent transport guarantee is verified against the real production turn function with an injected `BrokenPipeError` after one recorded effect. It is an integration test, not a destructive live Mail test.
- During SIGTERM polling the old PID still existed briefly, but it no longer owned the socket; a distinct PID owned the replacement socket and the old process was subsequently reaped. Final inspection found no Jaeger bridge zombie.

## Artifacts

- Machine evidence: `docs/verification/live-verification-evidence.json`
- Reproducible harness: `services/controller/scripts/live_verify_jaeger.py`
- Strict validator: `services/controller/scripts/validate_live_verification.py`

## Final statement

**The requested real decode, exact bridge replacement, context recovery, and read-only Mail operation are verified live. Whole-product verification is incomplete and must not be described as “fully working.”**

## Extended live verification — controls, commands, and long sessions

Executed after restarting `/Users/matthewjenkins/Applications/ARES.app` with
`--start-server`. The restarted app PID **37806**, controller PID **37812**,
and bridge PID **37824** all started after the working-tree edits. Controller
health returned ready with `qwen3.5:397b`.

### Passed live

- Cancellation: a real `{"op":"cancel"}` stopped an active 3,000-word turn
  in 1.88 seconds with `halt_reason=interrupted` and
  `halt_code=interrupted`.
- Steering: a real `{"op":"steer"}` reached an active turn and caused the
  exact requested `STEERED-LIVE-OK` response. Already-buffered model text was
  still delivered before the steered response, so steering is functional but
  not a clean replacement of buffered output.
- Approval deny: a real `request(kind=approval)` for
  `scheduling.schedule_prompt` received `deny`; no schedule was created.
- Approval allow: the same real request received `once`; a harmless one-shot
  verification schedule was created, then removed through a separately
  approved `cancel_schedule` call.
- Concurrent sessions: `con-a-a43fc0` recalled only `ALPHA-30f15c`; the
  simultaneous `con-b-1df084` recalled only `BRAVO-29f6a7`.
- Same-session concurrency: two simultaneous labeled facts were serialized;
  a subsequent turn returned exactly
  `LEFT=LEFT-0ef8e1;RIGHT=RIGHT-0acdec`.
- Prolonged session: 12 real model turns returned `ACK-1` through `ACK-11`,
  then exactly recalled `ANCHOR-d2375d17` on turn 12. Final context telemetry
  was `46,734 / 262,144`.
- Client disconnect: closing an attached client during an active turn returned
  `JaegerError: bridge exited mid-turn` to that client; a new client attached
  immediately and queried the serving model successfully.
- Lifecycle: five attach/close cycles completed in under 1 ms each, with no
  live reader threads, unhandled thread exceptions, or Jaeger bridge zombies.

### Slash-command audit

Every command deliberately supported by the app bridge returned successfully:
`/help`, `/tools`, `/skills`, `/facts`, `/plugins`, `/instance`, `/instances`,
`/board`, `/config`, `/auto`, `/mode`, `/model`, `/models`, bare `/goal`, and
bare `/steer`.

An unknown command returned the `/help` hint. Terminal-only or destructive
commands (`/status`, `/history`, `/factoryreset`, `/shutdown`, `/reboot`, and
`/download`) were refused by the bridge and did not execute. This is the
intended app/terminal boundary, not missing silent behavior.

### Additional defect fixed

Approval prompts for a turn submitted through an attached Unix-socket client
were incorrectly emitted to the bridge owner's stdio pipe. The initiating
client waited indefinitely. Jaeger now binds the confirmation provider to the
originating turn's output transport before running that turn. Live recheck:
an attached client received `perm1 / approval / scheduling.schedule_prompt`
and successfully denied it.

Regression results after this fix:

```text
Jaeger bridge/socket tests: 83 passed in 3.15s
ARES lifecycle/control/production/status tests: 31 passed in 13.23s
```

### Structured clarification and secret entry

The first extended run confirmed that the protocol declared `clarify` and
`secret` request kinds without a runtime producer. This was fixed with a
turn-scoped interaction sink and a `request_secret` tool; the installed app and
bridge were restarted again afterward.

Live ARES-controller results:

- `clarify` emitted `request(kind=clarify, id=perm3)`. ARES published a pending
  UI interaction for session `ares-clarify-5dd1e5`, resolved it with
  `controller-answer`, and the same in-flight model turn returned exactly
  `UI-CLARIFIED:controller-answer`.
- `request_secret` emitted `request(kind=secret, id=perm4)`. ARES published a
  secret-kind pending interaction, resolved it with a random canary, and the
  same turn returned exactly `UI-SECRET-RECEIVED`. The canary was absent from
  captured request frames, tool events, and the final reply.

Regression results after the interaction fix:

```text
Jaeger bridge/toolset/integrity tests: 96 passed in 3.53s
ARES lifecycle/control/production/status tests: 31 passed in 12.99s
```

The strict JSON validator artifact has not yet been regenerated from these
extended observations, so its older red result must not be used as the verdict
for this later run.

## Portability and personal-path audit

Production sources in ARES and JaegerAI were scanned separately from tests,
historical benchmark output, documentation, generated build files, and live
verification artifacts.

Behavior-changing findings removed:

- Knowledge Graph no longer invents
  `/Volumes/Jenkins_Robotics/03_Knowledge` when no source is configured.
- A configured knowledge folder is no longer silently rewritten to a named
  `03_Knowledge` child.
- Journal volume scanning no longer defaults to a named personal NAS mount;
  callers must provide the path being scanned.
- The web UI no longer advertises the personal NAS as a quick preset.
- Agent skill instructions no longer direct the runtime into contributor
  checkouts under `/home/teknium` or `/home/bb`.

Prevention added:

- ARES executable-source guard now rejects every `/Users/` literal rather than
  only two known usernames, with a narrow exemption for translated placeholder
  examples that are never read as filesystem paths.
- The guard also rejects the former organization-specific NAS literal.
- JaegerAI now scans executable Python plus agent-facing skill Markdown/YAML
  for concrete macOS/Linux user-home paths, excluding tests, references, and
  generated build directories.

Verification:

```text
ARES ownership + Knowledge Graph tests: 9 passed in 7.79s
Jaeger personal-path source guard: 1 passed in 0.31s
ARES.app restarted; /health status=ok, runtime_owner=mac_app
Jaeger status=ready, model=qwen3.5:397b
```

Named personal paths still present in historical benchmark result JSON,
development review notes, tests, and this machine-specific verification
evidence are non-executable artifacts. They do not participate in discovery,
runtime defaults, agent prompts, or filesystem access.
