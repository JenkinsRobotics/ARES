#!/usr/bin/env python3
"""Exercise the five ARES/Jaeger promises through the production backend seam.

This is intentionally smaller than the historical 32-phase harness. Every
pass in this artifact corresponds to an executed behavioral contract. A
boundary that is injected or not exercised is recorded as such, never promoted
to live evidence.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import secrets
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTROLLER = Path(__file__).resolve().parents[1]
ROOT = CONTROLLER.parents[1]
JAEGER_ROOT = Path(os.environ.get("ARES_JAEGER_SOURCE_DIR") or ROOT.parent / "JaegerAI").resolve()
EVIDENCE = ROOT / "docs" / "verification" / "jaeger-five-promises-evidence.json"
sys.path[:0] = [str(CONTROLLER), str(ROOT)]
os.chdir(CONTROLLER)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _socket_pid(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["lsof", "-F", "pc", str(path)], capture_output=True, text=True, timeout=10,
    )
    pid = None
    command = ""
    for line in proc.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit() and pid is None:
            pid = int(line[1:])
        elif line.startswith("c") and not command:
            command = line[1:]
    if pid is None:
        return {"pid": None, "verified": False, "command": command}
    ps = subprocess.run(
        ["ps", "-p", str(pid), "-o", "ppid=,command="],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    return {
        "pid": pid,
        "verified": "jaeger_ai.interfaces.bridge" in ps,
        "command": ps,
    }


class _ErrorCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.rows: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.rows.append(self.format(record))


def _drain_turn(channel: Any, *, timeout_s: float = 150.0) -> dict[str, Any]:
    subscriber, snapshot = channel.subscribe_with_snapshot()
    events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_s
    terminal = ""
    while time.monotonic() < deadline:
        try:
            item = subscriber.get(timeout=min(1.0, deadline - time.monotonic()))
        except queue.Empty:
            continue
        event, payload = item[0], item[1]
        row = {"event": str(event)}
        if isinstance(payload, dict):
            row.update({
                key: payload.get(key)
                for key in ("type", "message", "name", "event_type", "is_error")
                if payload.get(key) is not None
            })
            if event == "done":
                messages = ((payload.get("session") or {}).get("messages") or [])
                assistants = [m for m in messages if m.get("role") == "assistant"]
                row["assistant_text"] = str((assistants[-1] if assistants else {}).get("content") or "")
        events.append(row)
        if event in {"stream_end", "apperror", "error", "cancel"}:
            terminal = str(event)
            break
    channel.unsubscribe(subscriber)
    assistants = [row.get("assistant_text") for row in events if row.get("assistant_text")]
    return {
        "terminal": terminal or "timeout",
        "assistant_text": str(assistants[-1] if assistants else ""),
        "events": events,
        "subscription_snapshot": snapshot,
    }


def _send(session_id: str, text: str, backend: Any, *, model: str, provider: str) -> dict[str, Any]:
    from api import config
    from api.chat_runtime import start_session_turn

    started = time.monotonic()
    response = start_session_turn(
        session_id,
        text,
        source="webui",
        backend=backend,
        workspace=str(ROOT),
        model=model,
        model_provider=provider,
        explicit_model_pick=False,
    )
    stream_id = str(response.get("stream_id") or "")
    if not stream_id:
        return {"start": response, "terminal": "start_failed", "elapsed_s": 0.0}
    with config.STREAMS_LOCK:
        channel = config.STREAMS.get(stream_id)
    if channel is None:
        return {"start": response, "terminal": "missing_channel", "elapsed_s": 0.0}
    result = _drain_turn(channel)
    result["start"] = response
    result["elapsed_s"] = round(time.monotonic() - started, 3)
    return result


def main() -> int:
    os.environ.setdefault("ARES_JAEGER_INSTANCE", "ares")
    from api.models import new_session
    from api.providers.jaeger import streaming
    from api.providers.jaeger.backend import JaegerBackend
    from api.providers.jaeger.paths import jaeger_home

    errors = _ErrorCapture()
    logging.getLogger().addHandler(errors)
    started_at = _now()
    backend = JaegerBackend()
    worker, is_gateway, is_jaeger = backend.get_worker_target()
    serving = streaming.query_local_companion("serving_model", {})
    serving_row = (serving or {}).get("serving") or (serving or {}).get("configured") or {}
    model = str(serving_row.get("model") or "")
    provider = str(serving_row.get("provider") or "")
    tools_before = streaming.query_local_companion("list_tools", {})
    tool_rows = tools_before if isinstance(tools_before, list) else (tools_before or {}).get("tools", [])
    tool_names_before = [str(row.get("name") if isinstance(row, dict) else row) for row in tool_rows]

    session = new_session(
        workspace=str(ROOT), model=model, model_provider=provider, profile="default",
    )
    session.ares_backend = "jaeger_local"
    session.transcript_owner = "jaeger"
    codeword = f"PROMISE-{secrets.token_hex(4)}"
    second = f"SECOND-{secrets.token_hex(4)}"
    turn1 = _send(
        session.session_id,
        f"Remember exactly codeword {codeword} and second fact {second}. Reply only ACK.",
        backend, model=model, provider=provider,
    )
    turn2 = _send(
        session.session_id,
        "Reply only with the exact codeword I gave you.",
        backend, model=model, provider=provider,
    )
    turn3 = _send(
        session.session_id,
        "Reply only with the exact second fact I gave you.",
        backend, model=model, provider=provider,
    )

    tool_turn = _send(
        session.session_id,
        "You must call get_time now for timezone UTC. Do not estimate. Reply only with the returned timestamp.",
        backend, model=model, provider=provider,
    )
    tool_events_before = [
        row for row in tool_turn.get("events", [])
        if row.get("name") == "get_time" and row.get("event") == "tool"
    ]

    # Resolve and terminate only the verified listener for the selected instance.
    socket_path = Path(jaeger_home()) / ".jaeger_ai" / "instances" / "ares" / "run" / "bridge.sock"
    before = _socket_pid(socket_path)
    restart_error = ""
    if before.get("verified"):
        os.kill(int(before["pid"]), signal.SIGTERM)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and _socket_pid(socket_path).get("pid") == before.get("pid"):
            time.sleep(0.2)
        # Controller worker eviction is represented by dropping its dead cached
        # client; the next turn must use the ordinary production backend path.
        streaming.reset_jaeger_runtime()
    else:
        restart_error = "listener PID could not be verified; no signal sent"
    after_restart = _send(
        session.session_id,
        "After the runtime restart, reply only with the exact codeword I gave you.",
        backend, model=model, provider=provider,
    )
    tool_after_restart = _send(
        session.session_id,
        "After the restart, call get_time for Pacific/Kiritimati now. A new tool call is required; do not reuse or convert any earlier timestamp.",
        backend, model=model, provider=provider,
    )
    tool_events_after = [
        row for row in tool_after_restart.get("events", [])
        if row.get("name") == "get_time" and row.get("event") == "tool"
    ]
    after = _socket_pid(socket_path)
    tools_after = streaming.query_local_companion("list_tools", {})
    rows_after = tools_after if isinstance(tools_after, list) else (tools_after or {}).get("tools", [])
    tool_names_after = [str(row.get("name") if isinstance(row, dict) else row) for row in rows_after]

    promises = {
        "multi_turn_memory": {
            "expected": {"turn2": codeword, "turn3": second},
            "actual": {"turn2": turn2.get("assistant_text"), "turn3": turn3.get("assistant_text")},
            "result": "pass" if codeword in turn2.get("assistant_text", "") and second in turn3.get("assistant_text", "") else "fail",
            "boundary": "real JaegerBackend → start_session_turn → streaming worker → bridge → model",
        },
        "session_survives_worker_restart": {
            "expected": {"different_pid": True, "recall": codeword},
            "actual": {"before": before, "after": after, "reply": after_restart.get("assistant_text"), "preflight_error": restart_error},
            "result": "pass" if before.get("verified") and after.get("pid") not in {None, before.get("pid")} and codeword in after_restart.get("assistant_text", "") else "fail",
            "boundary": "physical verified bridge termination + ARES cache eviction + next production turn",
        },
        "tools_remain_available": {
            "expected": "get_time running/completed events before and after restart",
            "actual": {
                "inventory_before": tool_names_before,
                "inventory_after": tool_names_after,
                "tool_events_before": tool_events_before,
                "tool_events_after": tool_events_after,
            },
            "result": "pass" if len(tool_events_before) >= 2 and len(tool_events_after) >= 2 else "fail",
            "boundary": "harmless live tool calls; inventory is recorded separately because a pre-boot empty inventory is not proof of refusal",
        },
        "successful_requests_have_no_hidden_exceptions": {
            "expected": "terminal stream_end for successful turns and no ERROR log records",
            "actual": {"terminals": [turn1.get("terminal"), turn2.get("terminal"), turn3.get("terminal"), tool_turn.get("terminal"), after_restart.get("terminal"), tool_after_restart.get("terminal")], "error_logs": errors.rows},
            "result": "pass" if all(row.get("terminal") == "stream_end" for row in (turn1, turn2, turn3, tool_turn, after_restart, tool_after_restart)) and not errors.rows else "fail",
            "boundary": "in-process ARES service logs; installed-app logs not captured",
        },
        "production_uses_gateway_path": {
            "expected": "run_jaeger_streaming, is_gateway=True, is_jaeger=True",
            "actual": {"worker": f"{worker.__module__}.{worker.__name__}", "is_gateway": is_gateway, "is_jaeger": is_jaeger},
            "result": "pass" if worker is streaming.run_jaeger_streaming and is_gateway and is_jaeger else "fail",
            "boundary": "real JaegerBackend object used for every turn above",
        },
    }
    evidence = {
        "schema": "ares-jaeger-five-promises/v1",
        "started_at": started_at,
        "finished_at": _now(),
        "command": [sys.executable, str(Path(__file__).resolve())],
        "configuration": {"instance": "ares", "model": model, "provider": provider, "workspace": str(ROOT)},
        "commits": {"ares": _git(ROOT, "rev-parse", "HEAD"), "jaeger": _git(JAEGER_ROOT, "rev-parse", "HEAD")},
        "dirty_worktrees": {"ares": bool(_git(ROOT, "status", "--porcelain")), "jaeger": bool(_git(JAEGER_ROOT, "status", "--porcelain"))},
        "promises": promises,
        "turns": {"turn1": turn1, "turn2": turn2, "turn3": turn3, "tool": tool_turn, "after_restart": after_restart, "tool_after_restart": tool_after_restart},
        "mocked_boundaries": [],
        "untested_or_injected": [
            "Browser DOM and HTTP/SSE route were not automated; start_session_turn is the UI-facing service seam.",
            "Provider timeout, malformed provider payload, and post-side-effect transport loss remain production-object injected tests, not destructive live provider faults.",
            "Installed ARES.app logs were not captured; error-log evidence covers this verifier process.",
        ],
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    failed = [name for name, row in promises.items() if row["result"] != "pass"]
    print(json.dumps({"evidence": str(EVIDENCE), "failed": failed, "promises": promises}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
