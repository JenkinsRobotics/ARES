#!/usr/bin/env python3
"""Record whether the running installed app uses the expected saved source."""

from __future__ import annotations

import json
import plistlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = Path.home() / "Applications" / "ARES.app"
OUT = ROOT / "docs" / "verification" / "installed-app-evidence.json"


def _run(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=20).stdout.strip()


def main() -> int:
    expected = _run("git", "-C", str(ROOT), "rev-parse", "HEAD")
    plist_path = APP / "Contents" / "Info.plist"
    plist = plistlib.loads(plist_path.read_bytes()) if plist_path.exists() else {}
    bundled = str(plist.get("ARESSourceCommit") or "")
    bundle_clean = plist.get("ARESSourceDirty") is False
    app_rows = [line for line in _run("pgrep", "-alf", str(APP / "Contents/MacOS/ARES")).splitlines() if line]
    controller_rows = []
    for line in _run("pgrep", "-alf", "uvicorn fastapi_app.main:app").splitlines():
        pid = line.split(maxsplit=1)[0]
        cwd = _run("lsof", "-a", "-p", pid, "-d", "cwd", "-Fn")
        paths = [row[1:] for row in cwd.splitlines() if row.startswith("n")]
        if paths and Path(paths[0]).resolve() == (ROOT / "services/controller").resolve():
            controller_rows.append({"process": line, "cwd": paths[0]})
    relevant_clean = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--quiet", "HEAD", "--", "apps/web", "services/controller"],
    ).returncode == 0
    # Unified log output is bounded and redacted to error/fault messages. Empty
    # output means no matching installed-app errors were recorded in the window.
    log_text = _run(
        "/usr/bin/log", "show", "--last", "10m", "--style", "compact",
        "--predicate", 'process == "ARES" AND (messageType == error OR messageType == fault)',
    )
    errors = [line for line in log_text.splitlines() if line and not line.startswith("Timestamp")]
    checks = {
        "bundle_exists": APP.exists(),
        "bundle_commit_matches": bundled == expected,
        "bundle_was_built_clean": bundle_clean,
        "installed_process_running": bool(app_rows),
        "controller_uses_current_checkout": bool(controller_rows),
        "web_and_controller_match_saved_commit": relevant_clean,
        "no_installed_app_errors_last_10m": not errors,
    }
    evidence = {
        "schema": "ares-installed-app-evidence/v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "command": [sys.executable, str(Path(__file__).resolve())],
        "expected_commit": expected,
        "bundle_commit": bundled,
        "checks": checks,
        "app_processes": app_rows,
        "controller_processes": controller_rows,
        "error_logs": errors,
        "result": "pass" if all(checks.values()) else "fail",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if evidence["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
