#!/usr/bin/env python3
"""Strict validator for live-verification-evidence.json.

Exit 0 only when every required phase and promise is present, complete, and
passed. Names without evidence fields fail.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_PHASES = [
    "harness_diagnosis",
    "production_object_pytest",
    "routing",
    "attach_candidates",
    "static_contracts",
    "installed_runtime_snapshot",
    "bridge_start",
    "bridge_queries",
    "turn1",
    "turn2",
    "turn3",
    "explicit_session_resume",
    "mail_readonly",
    "bridge_death_preflight",
    "bridge_death",
    "recall_after_bridge_death",
    "tools_after_bridge_death",
    "mail_after_replacement",
    "non_idempotent_failure",
    "cancel_live",
    "steer_live",
    "clarification_live",
    "approval_deny_live",
    "approval_allow_live",
    "secret_redaction_live",
    "concurrent_sessions",
    "same_session_concurrency",
    "client_disconnect",
    "attached_client_close",
    "lifecycle_cycles",
    "installed_app_verification",
    "process_state_after",
]

REQUIRED_PROMISES = [
    "production routing selects Jaeger gateway",
    "ARES sends only the new user turn",
    "live agent remembers turns 2 and 3",
    "explicit saved-session resume restores context",
    "physical bridge replacement restores context",
    "telemetry cannot convert success into failure",
    "bookkeeping cannot convert success into failure",
    "tool inventory survives bridge replacement",
    "live Mail tool works before replacement",
    "live Mail tool works after replacement",
    "transport failure does not duplicate a committed effect",
    "cancellation reaches the live runtime",
    "steering reaches the live runtime",
    "clarification round-trip works",
    "approval deny works",
    "approval allow works in a harmless isolated operation",
    "secret values are redacted",
    "concurrent sessions remain isolated",
    "same-session concurrent turns are serialized or rejected safely",
    "attached-client close produces no unhandled exception",
    "lifecycle cycles leave no zombies or leaked bridge processes",
    "installed application runs the tested code",
    "final runtime status is healthy",
]

PHASE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "harness_diagnosis": ("last_completed_phase", "next_attempted_phase", "reason", "repair"),
    "turn1": ("expected", "actual", "result"),
    "turn2": ("expected", "actual", "result"),
    "turn3": ("expected", "actual", "result"),
    "mail_readonly": ("tool_events", "result"),
    "mail_after_replacement": ("tool_events", "result"),
    "bridge_death_preflight": ("pid", "ppid", "command", "instance", "socket"),
    "bridge_death": ("pid_before", "pid_after", "result"),
    "recall_after_bridge_death": ("token", "response", "result"),
    "non_idempotent_failure": ("ledger_count", "result"),
    "process_state_after": ("zombie_count", "bridge_health"),
    "lifecycle_cycles": ("cycles", "result"),
    "installed_app_verification": ("runtime_path", "result"),
    "cancel_live": ("protocol_event", "result"),
    "steer_live": ("protocol_event", "result"),
    "clarification_live": ("protocol_event", "result"),
    "approval_deny_live": ("protocol_event", "result"),
    "approval_allow_live": ("protocol_event", "result"),
    "secret_redaction_live": ("protocol_event", "result"),
}


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _phase_skipped(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return True
    result = str(payload.get("result") or "").lower()
    if result in {"skip", "skipped"}:
        return True
    if payload.get("skipped") is True:
        return True
    return False


def _promise_result(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("result") or "").strip().lower()


def validate(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["evidence is not an object"]

    started = _parse_ts(data.get("started_at"))
    finished = _parse_ts(data.get("finished_at"))
    if not data.get("started_at"):
        errors.append("started_at missing")
    if data.get("finished_at") in (None, "", False):
        errors.append("finished_at missing or null")
    if started and finished and finished <= started:
        errors.append("finished_at is not later than started_at")

    if not data.get("commands"):
        errors.append("commands is empty")
    if "findings" not in data:
        errors.append("findings missing")
    if "mocked_boundaries" not in data:
        errors.append("mocked_boundaries missing")
    if "untested" not in data:
        errors.append("untested missing")

    process_after = data.get("process_state_after")
    if not process_after:
        errors.append("process_state_after is empty")

    phases = data.get("phases")
    if not isinstance(phases, dict):
        errors.append("phases missing")
        phases = {}

    for name in REQUIRED_PHASES:
        payload = phases.get(name)
        if payload is None:
            errors.append(f"required phase missing: {name}")
            continue
        if not isinstance(payload, dict) or len(payload) < 2:
            errors.append(f"phase {name} has no evidence fields")
            continue
        if _phase_skipped(payload):
            errors.append(f"required live phase skipped: {name}")
            continue
        needed = PHASE_REQUIRED_FIELDS.get(name, ("result",))
        missing = [field for field in needed if field not in payload]
        if missing:
            errors.append(f"phase {name} missing fields: {', '.join(missing)}")
        result = str(payload.get("result") or "").lower()
        if "result" in needed and result not in {"pass", "ok", "true"}:
            errors.append(f"phase {name} result is not pass ({payload.get('result')!r})")

        if name in {"mail_readonly", "mail_after_replacement"}:
            events = payload.get("tool_events")
            if not isinstance(events, list) or not events:
                errors.append(f"phase {name} missing captured list_mailboxes tool events")
            elif not any("list_mailboxes" in str(item) for item in events):
                errors.append(f"phase {name} tool events do not include list_mailboxes")

        if name == "recall_after_bridge_death":
            token = str(payload.get("token") or "")
            response = str(payload.get("response") or "")
            if not token or token not in response:
                errors.append("recall_after_bridge_death token not in real model response")

        if name == "non_idempotent_failure":
            if payload.get("ledger_count") != 1:
                errors.append("non_idempotent_failure ledger_count is not 1")

        if name == "bridge_death":
            if not payload.get("pid_before") or not payload.get("pid_after"):
                errors.append("bridge_death missing before/after PIDs")

        if name == "process_state_after":
            if "zombie_count" not in payload or "bridge_health" not in payload:
                errors.append("process_state_after missing zombie_count or bridge_health")

    promises = data.get("promises")
    if not isinstance(promises, dict):
        errors.append("promises missing")
        promises = {}
    for name in REQUIRED_PROMISES:
        payload = promises.get(name)
        if payload is None:
            errors.append(f"required promise absent: {name}")
            continue
        result = _promise_result(payload)
        if result != "pass":
            errors.append(f"required promise not pass: {name} ({result or 'missing result'})")
        if not isinstance(payload, dict) or "expected" not in payload or "actual" not in payload:
            errors.append(f"promise {name} missing expected/actual")
    return errors


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0] if args else "docs/verification/live-verification-evidence.json")
    if not path.is_absolute():
        here = Path(__file__).resolve()
        repo = here.parents[2] if here.parents[1].name == "scripts" else here.parents[3]
        # parents[1]==scripts => parents[2]==controller; evidence lives at repo root.
        repo_root = here.parents[3] if (here.parents[3] / "docs").exists() else here.parents[2]
        for candidate in (
            (Path.cwd() / path).resolve(),
            (repo_root / path).resolve(),
            (repo_root / "docs" / "verification" / "live-verification-evidence.json"),
        ):
            if candidate.exists():
                path = candidate
                break
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED to read {path}: {exc}", file=sys.stderr)
        return 2
    errors = validate(data)
    if errors:
        print(f"INVALID {path} ({len(errors)} errors)", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return 1
    print(f"VALID {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
