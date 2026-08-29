#!/usr/bin/env python3
"""Record whether the running installed app uses the expected saved source."""

from __future__ import annotations

import json
import plistlib
import re
import subprocess
import sys
import time
import urllib.request
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
    app_pid = app_rows[0].split(maxsplit=1)[0] if app_rows else ""
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
    health = {"checked": False, "status": None, "port": None}
    for row in controller_rows:
        match = re.search(r"--port\s+(\d+)", row["process"])
        if not match:
            continue
        health["port"] = int(match.group(1))
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{health['port']}/health", timeout=5) as response:
                health.update({"checked": True, "status": response.status})
        except Exception as exc:  # recorded as evidence, not hidden
            health.update({"checked": True, "error": str(exc)})
        break
    observation_started = datetime.now(timezone.utc).isoformat()
    time.sleep(3)
    # Observe only the currently running installed process after controller
    # health, excluding launch-time connection polling and stale app instances.
    log_text = _run(
        "/usr/bin/log", "show", "--start", observation_started, "--style", "compact",
        "--predicate", f'processIdentifier == {app_pid or 0} AND (messageType == error OR messageType == fault)',
    )
    errors = [line for line in log_text.splitlines() if line and not line.startswith("Timestamp")]
    checks = {
        "bundle_exists": APP.exists(),
        "bundle_commit_matches": bundled == expected,
        "bundle_was_built_clean": bundle_clean,
        "installed_process_running": bool(app_rows),
        "controller_uses_current_checkout": bool(controller_rows),
        "web_and_controller_match_saved_commit": relevant_clean,
        "controller_health_responded": health.get("status") == 200,
        "no_installed_app_errors_during_observation": not errors,
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
        "controller_health": health,
        "log_observation_started": observation_started,
        "error_logs": errors,
        "result": "pass" if all(checks.values()) else "fail",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if evidence["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
