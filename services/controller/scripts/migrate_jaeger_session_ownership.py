#!/usr/bin/env python3
"""Classify and migrate legacy dual-written ARES/Jaeger conversations.

Dry-run is the default. ``--apply`` removes ARES transcript copies only when
the ordered user/assistant text exactly matches Jaeger's canonical history.
ARES-owned UI metadata remains in the sidecar.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


CONTROLLER_ROOT = Path(__file__).resolve().parents[1]
if str(CONTROLLER_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTROLLER_ROOT))


def _normalized_ares(messages) -> list[tuple[str, str]]:
    return [
        (str(row.get("role") or ""), " ".join(str(row.get("content") or "").split()))
        for row in (messages or [])
        if isinstance(row, dict) and row.get("role") in {"user", "assistant"}
    ]


def _normalized_jaeger(messages) -> list[tuple[str, str]]:
    return [
        (str(row.get("role") or ""), " ".join(str(row.get("text") or "").split()))
        for row in (messages or [])
        if isinstance(row, dict) and row.get("role") in {"user", "assistant"}
    ]


def _is_subsequence(values: list[str], candidates: list[str]) -> bool:
    iterator = iter(candidates)
    return all(any(candidate == value for candidate in iterator) for value in values)


def migrate(*, apply: bool) -> dict:
    from api.config import SESSION_DIR
    from api.models import Session, delete_cli_session
    from api.providers.jaeger.gateway_streaming import (
        _reset_local_bridge_clients,
        command_local_companion,
        query_local_companion,
    )

    runtime_rows = query_local_companion("list_sessions", {"limit": 100_000}) or []
    runtime_ids = {
        str(row.get("id"))
        for row in runtime_rows
        if isinstance(row, dict) and row.get("id")
    }
    report = {
        "contract_version": 2,
        "apply": apply,
        "canonical": [],
        "reconcilable": [],
        "ares_only": [],
        "jaeger_only": sorted(runtime_ids),
        "conflicts": [],
    }
    try:
        for path in sorted(SESSION_DIR.glob("*.json")):
            if path.name.startswith("_"):
                continue
            session = Session.load(path.stem)
            if session is None:
                continue
            session_id = str(session.session_id)
            messages = list(session.messages or [])
            looks_jaeger = (
                getattr(session, "transcript_owner", None) == "jaeger"
                or getattr(session, "ares_backend", None) == "jaeger_local"
                or any(
                    isinstance(row, dict) and row.get("backend") == "jros"
                    for row in messages
                )
            )
            if not looks_jaeger or session_id not in runtime_ids:
                report["ares_only"].append(session_id)
                continue
            runtime_messages = query_local_companion(
                "load_session", {"id": session_id, "resume": False}
            ) or []
            local_normalized = _normalized_ares(messages)
            runtime_normalized = _normalized_jaeger(runtime_messages)
            if local_normalized and local_normalized != runtime_normalized:
                local_users = [text for role, text in local_normalized if role == "user"]
                runtime_users = [text for role, text in runtime_normalized if role == "user"]
                local_assistants = [
                    text for role, text in local_normalized if role == "assistant"
                ]
                runtime_assistants = [
                    text for role, text in runtime_normalized if role == "assistant"
                ]
                safely_reconcilable = (
                    len(local_users) == len(runtime_users)
                    and _is_subsequence(local_assistants, runtime_assistants)
                )
                if not safely_reconcilable:
                    report["conflicts"].append({
                        "id": session_id,
                        "ares_messages": len(local_normalized),
                        "jaeger_messages": len(runtime_normalized),
                    })
                    continue
                report["reconcilable"].append(session_id)
                if apply:
                    command_local_companion("reconcile_session_transcript", {
                        "id": session_id,
                        "user_messages": local_users,
                    })
            report["canonical"].append(session_id)
            if apply:
                session.transcript_owner = "jaeger"
                session.runtime_message_count = len(runtime_normalized)
                session.messages = []
                session.context_messages = []
                session.tool_calls = []
                session.save(touch_updated_at=False)
                session.path.with_suffix(".json.bak").unlink(missing_ok=True)
                delete_cli_session(session_id)
            report["jaeger_only"].remove(session_id)
    finally:
        _reset_local_bridge_clients()
    for key in ("canonical", "reconcilable", "ares_only", "jaeger_only"):
        report[key] = sorted(report[key])
    report["counts"] = {
        key: len(report[key])
        for key in ("canonical", "reconcilable", "ares_only", "jaeger_only", "conflicts")
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = migrate(apply=args.apply)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
