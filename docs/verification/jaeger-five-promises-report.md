# ARES ↔ Jaeger five-promise audit

Date: 2026-08-26. This report is scoped to the five named user-visible
promises. It does not certify the whole application.

## Runtime evidence

Exact command:

```bash
cd services/controller
.venv/bin/python scripts/verify_jaeger_promises.py
```

Configuration and revisions:

| Item | Value |
|---|---|
| ARES commit | `89b99cc1b972b89b51205c6dbcede36d5318c9a3` plus recorded dirty-tree changes |
| Jaeger commit | `87ed89a4ea6fe9a9952623d497c68e7d6fb21599` plus recorded dirty-tree changes |
| Instance | `ares` |
| Provider/model | `ollama-cloud` / `qwen3.5:397b` |
| Execution window | `2026-08-26T07:29:15Z`–`07:31:05Z` |
| Machine artifact | `docs/verification/jaeger-five-promises-evidence.json` |

Observed results:

| Promise | Expected | Actual | Result |
|---|---|---|---|
| Multi-turn memory | Turn 2 recalls `PROMISE-a78adfdf`; turn 3 recalls `SECOND-c9bb5043` | Exact values returned through the real production backend | Pass |
| Session survives worker restart | Verified listener PID changes and the replacement recalls the pre-restart codeword | PID `1407 → 1584`; exact codeword returned | Pass |
| Tools remain available | `get_time` emits running/completed events before and after restart | Both event pairs captured; no tool error | Pass |
| Successful requests have no hidden exceptions | Six successful turns end with `stream_end`; no service-process ERROR records | Six `stream_end`; captured ERROR list empty | Pass within the verifier process |
| Production uses the gateway path | Real backend selects `run_jaeger_streaming` with both routing flags true | Exact worker object; `is_gateway=true`, `is_jaeger=true` | Pass |

An earlier attempt intentionally requested `list_mailboxes`; the model replied
`TOOL-OK` without calling it. That attempt failed the tool promise. The final
probe uses `get_time` with a result that must be freshly obtained and requires
actual running/completed tool frames. This is why a textual claim or non-empty
inventory does not count as tool evidence.

## Real path traced

```text
Browser send contract
  → chat_runtime.start_session_turn
  → session/model/workspace resolution
  → real JaegerBackend.get_worker_target
  → clean user prompt because is_gateway=True
  → run_jaeger_streaming worker thread
  → _run_local_jaeger_turn
  → cached/attached JaegerClient
  → versioned NDJSON bridge
  → Jaeger run_turn / model / tool callbacks
  → Jaeger authoritative transcript
  → ARES append-only projection and run journal
  → done + stream_end
```

The live verifier enters at `start_session_turn`, not at the lower streaming
helper. It therefore exercises the real backend selection, prompt-shape flag,
worker thread, stream channel, persistence projection, and terminal events.

## Flags, defaults, and lifecycle boundaries

- `JaegerBackend.get_worker_target()` returns
  `(run_jaeger_streaming, True, True)`. The second value is behavior-changing:
  false would serialize ARES history back into a runtime that owns its own
  transcript.
- `ARES_JAEGER_INSTANCE` wins over the sticky Jaeger instance; the verifier
  explicitly uses `ares` so setup queries and turns share one cache key.
- A new bridge process hydrates a session with
  `load_session(id, resume=True)` once per bridge/cache lifecycle. Display-only
  loads use `resume=False`.
- The bridge client attaches to the selected instance socket before spawning.
  The restart probe signals only a listener whose `lsof` PID and `ps` command
  identify `jaeger_ai.interfaces.bridge`.
- Dead-transport turns are not blindly replayed because a consequential tool
  may have committed before the disconnect. The next user turn performs
  hydration.
- Successful telemetry/bookkeeping is best-effort and must not evict a client
  or discard an answer. Production-object tests inject failures at those
  boundaries.
- `tools()` retains its legacy list-only contract, where `[]` is ambiguous.
  `inventory().active_execution.tools_unknown` is authoritative, and the
  legacy adapters response now projects that flag instead of hiding it.
- The top-level worker wrapper publishes boot exceptions to the stream and
  clears pending session state. `run_jaeger_streaming` converts turn failures
  to visible `apperror` events; its `finally` releases stream and active-run
  state.

## Test classification

### Keep

- Real `JaegerBackend` routing-object test.
- Clean-prompt test through `start_session_turn`; it mocks generation but pins
  the behavior-changing gateway seam.
- Telemetry/bookkeeping exception tests against `_run_local_jaeger_turn`.
- Dead-transport no-replay and next-turn hydration tests.
- Attach/close lifecycle tests and bridge protocol/socket suites.
- The new live verifier for three-turn continuity, verified process
  replacement, real tool events, persistence projection, and terminal logs.

### Repair or correctly label

- `test_production_jaeger_multi_turn_sends_clean_user_text` is a prompt-shape
  integration test, not proof of memory; its worker is mocked.
- Provider timeout, malformed provider response, and post-side-effect transport
  loss tests inject the provider/client boundary. Keep them, but do not call
  them live provider evidence.
- The legacy 32-phase harness does not execute all 32 phases. Its header has
  been corrected and its validator remains red when required phases are absent.

### Obsolete assertions removed from the current contract

- A non-empty tool inventory alone does not prove tools are callable.
- `is_gateway=True` on a fake backend does not prove the real Jaeger backend
  selects that path.
- Comments and status text are not evidence.

## Adversarial scenario status

| Scenario | Evidence |
|---|---|
| Second and third turns | Executed live through real backend; exact recall |
| Restart between turns | Verified listener terminated and replaced; exact recall |
| Worker eviction | ARES cached client reset after physical death; next production turn succeeded |
| Tool loading and reuse | Real `get_time` callbacks before and after restart |
| Malformed response | Injected production-object test; not a live malformed provider |
| Provider timeout/reconnection | Timeout and broken-transport tests are injected; physical bridge reconnection executed live |

## Boundaries not proved by this run

- Browser DOM and the HTTP/SSE router were not automated. The run starts at
  the UI-facing `start_session_turn` service seam.
- Installed `ARES.app` logs were not captured. “No hidden exceptions” means no
  ERROR records in the verifier process and valid terminal events for its six
  turns.
- No destructive tool was invoked. The live tool probe is read-only.
- A real provider timeout and malformed provider payload were not induced;
  their tests use injected failures and are reported that way.

Precise conclusion: verified three-turn continuity against the real
`JaegerBackend` at the revisions above, verified exact recall after replacing
the bridge listener, verified real tool events before and after replacement,
and observed no ERROR records in the verifier process. The untested boundaries
remain listed above.

## Regression commands

ARES production-object and projection tests:

```text
cd services/controller
.venv/bin/python -m pytest -q \
  tests/test_legacy_adapter_tool_truth.py \
  tests/test_jaeger_production_promises.py \
  tests/test_jaeger_attach_and_status_honesty.py \
  tests/test_jaeger_client_lifecycle.py \
  tests/test_jaeger_streaming_reliability.py \
  tests/test_jaeger_ownership_literals.py

35 passed in 19.49s
```

Jaeger bridge/loop tests, with the required isolated instance home:

```text
isolated_home=$(mktemp -d /tmp/jaeger-audit-tests.XXXXXX)
JAEGER_HOME="$isolated_home" JAEGER_INSTANCE_NAME=test-audit \
  .venv/bin/python -m pytest -q \
  dev/tests/jaeger_ai/core/test_bridge_socket.py \
  dev/tests/jaeger_ai/interfaces/test_bridge.py \
  packages/jaeger-agent/tests/test_tool_result_safety.py \
  packages/jaeger-agent/tests/test_run_turn.py

109 passed in 3.32s
```

The first Jaeger invocation ran the same 109 assertions but returned failure
because its isolation guard observed the concurrently running live `ares`
instance changing `.lock`, `audit.log`, `manifest.json`, and SQLite WAL files.
That was a test-configuration failure, not reported as a green run. Pointing
`JAEGER_HOME` at a temporary instance produced the result above.
