"""Bounded, isolated stage runner for the ARES/Jaeger field test.

Every stage runs under a deadline, in its own process group, with output
streamed rather than buffered — a 25-minute stage that prints nothing until
it exits is indistinguishable from a hang, which is exactly the failure the
field test exists to catch.

macOS has no ``timeout``/``gtimeout`` in a default install, so the deadline
is enforced here rather than by coreutils.

On expiry the whole PROCESS GROUP is killed, not just the direct child:
pytest-xdist workers, uvicorn reloaders and bridge subprocesses all
outlive a bare ``kill(pid)`` and would leak into later stages.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def free_port() -> int:
    """Ask the kernel for a port nothing is using.

    Bind-and-release races in principle; in practice it is the only
    portable option, and the alternative — a hardcoded port — is what puts
    a test on top of the operator's live 8788 server.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(s.getsockname()[1])


def run_stage(name: str, cmd: list[str], timeout: float,
              env: dict[str, str] | None = None,
              cwd: str | None = None,
              log_path: Path | None = None) -> dict:
    """Run one stage. Returns a record; never raises on stage failure."""
    started = time.time()
    merged = {**os.environ, **(env or {})}
    log = log_path.open("w", encoding="utf-8") if log_path else None

    proc = subprocess.Popen(
        cmd, cwd=cwd, env=merged,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, start_new_session=True,
    )

    timed_out = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:                 # streams as it arrives
            sys.stdout.write(f"    │ {line}")
            sys.stdout.flush()
            if log:
                log.write(line)
            if time.time() - started > timeout:
                timed_out = True
                break
        if not timed_out:
            proc.wait(timeout=max(1.0, timeout - (time.time() - started)))
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        if timed_out or proc.poll() is None:
            _kill_group(proc)
            timed_out = True
        if log:
            log.close()

    elapsed = time.time() - started
    rc = proc.returncode if proc.returncode is not None else -1
    return {
        "stage": name,
        "status": "timeout" if timed_out else ("pass" if rc == 0 else "fail"),
        "exit_code": rc,
        "seconds": round(elapsed, 2),
        "timeout_s": timeout,
        "log": str(log_path) if log_path else None,
    }


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGTERM the group, then SIGKILL what ignored it."""
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


def main() -> int:
    ap = argparse.ArgumentParser(description="run one bounded field-test stage")
    ap.add_argument("--name", required=True)
    ap.add_argument("--timeout", type=float, required=True)
    ap.add_argument("--log", default=None)
    ap.add_argument("--cwd", default=None)
    ap.add_argument("--report", default=None, help="append the record here as JSONL")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()

    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        print("no command given", file=sys.stderr)
        return 2

    rec = run_stage(args.name, cmd, args.timeout,
                    cwd=args.cwd,
                    log_path=Path(args.log) if args.log else None)
    if args.report:
        with open(args.report, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    return 0 if rec["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
