#!/usr/bin/env python3
"""Install launchd jobs for Agentgateway and managed Apple containers."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path


def write_plist(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".plist.tmp")
    with temporary.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=False)
    os.replace(temporary, path)


def install(label: str, arguments: list[str], log_dir: Path, keep_alive: bool) -> None:
    launch_dir = Path.home() / "Library" / "LaunchAgents"
    launch_dir.mkdir(parents=True, exist_ok=True)
    plist = launch_dir / f"{label}.plist"
    write_plist(
        plist,
        {
            "Label": label,
            "ProgramArguments": arguments,
            "RunAtLoad": True,
            "KeepAlive": keep_alive,
            "ProcessType": "Background",
            "ThrottleInterval": 10,
            "StandardOutPath": str(log_dir / f"{label}.log"),
            "StandardErrorPath": str(log_dir / f"{label}.err.log"),
        },
    )
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist)], check=False, capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    print(f"Installed {label}")


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    state = Path(os.environ.get("ARES_HOME") or Path.home() / ".ares")
    log_dir = state / "logs"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_dir.chmod(0o700)
    install(
        "com.jenkinsrobotics.ares-agentgateway",
        ["/bin/zsh", str(repo / "scripts" / "run-agentgateway.sh")],
        log_dir,
        True,
    )
    install(
        "com.jenkinsrobotics.ares-containers",
        ["/bin/zsh", str(repo / "scripts" / "start-managed-containers.sh")],
        log_dir,
        False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
