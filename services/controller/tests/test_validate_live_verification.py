"""The incomplete live-verification JSON must fail the strict validator."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from scripts.validate_live_verification import (
    REQUIRED_PHASES,
    REQUIRED_PROMISES,
    validate,
    main as validate_main,
)

CONTROLLER = Path(__file__).resolve().parents[1]
LIVE_JSON = CONTROLLER / "tests" / "fixtures" / "incomplete_live_verification.json"


def _valid_fixture() -> dict:
    now = datetime.now(timezone.utc)
    later = now + timedelta(seconds=10)
    phases = {}
    for name in REQUIRED_PHASES:
        phases[name] = {
            "recorded_at": now.isoformat(),
            "result": "pass",
            "expected": "ok",
            "actual": "ok",
            "last_completed_phase": "turn2",
            "next_attempted_phase": "turn3",
            "reason": "none",
            "repair": "none",
            "tool_events": [{"name": "list_mailboxes", "phase": "done"}],
            "pid": 1,
            "ppid": 2,
            "command": "python -m jaeger_ai.interfaces.bridge",
            "instance": "liveverify",
            "socket": "/tmp/bridge.sock",
            "pid_before": 11,
            "pid_after": 12,
            "token": "abc",
            "response": "abc recalled",
            "ledger_count": 1,
            "zombie_count": 0,
            "bridge_health": "ok",
            "cycles": [{"i": 0}],
            "runtime_path": "/tmp/ares",
            "protocol_event": {"op": "cancel"},
        }
    promises = {
        name: {"result": "pass", "expected": "x", "actual": "x"}
        for name in REQUIRED_PROMISES
    }
    return {
        "started_at": now.isoformat(),
        "finished_at": later.isoformat(),
        "commands": [{"argv": ["true"], "returncode": 0}],
        "findings": [],
        "mocked_boundaries": [],
        "untested": [],
        "process_state_after": {"zombie_count": 0, "bridge_health": "ok"},
        "phases": phases,
        "promises": promises,
    }


def test_current_incomplete_json_fails():
    data = json.loads(LIVE_JSON.read_text(encoding="utf-8"))
    errors = validate(data)
    assert errors, "incomplete live evidence must fail the validator"
    joined = "\n".join(errors)
    assert "finished_at missing or null" in joined


def test_missing_required_phase_fails():
    data = _valid_fixture()
    del data["phases"]["turn3"]
    errors = validate(data)
    assert any("turn3" in item for item in errors)


def test_finished_at_null_fails():
    data = _valid_fixture()
    data["finished_at"] = None
    errors = validate(data)
    assert any("finished_at" in item for item in errors)


def test_failed_promise_fails():
    data = _valid_fixture()
    name = REQUIRED_PROMISES[0]
    data["promises"][name]["result"] = "fail"
    errors = validate(data)
    assert any(name in item for item in errors)


def test_fabricated_phase_without_evidence_fields_fails():
    data = _valid_fixture()
    data["phases"]["mail_readonly"] = {"recorded_at": datetime.now(timezone.utc).isoformat()}
    errors = validate(data)
    assert any("mail_readonly" in item for item in errors)


def test_complete_valid_fixture_passes():
    errors = validate(_valid_fixture())
    assert errors == []


def test_validator_cli_rejects_incomplete_json(tmp_path, capsys):
    src = LIVE_JSON
    assert src.exists()
    code = validate_main([str(src)])
    assert code == 1
    err = capsys.readouterr().err
    assert "INVALID" in err
