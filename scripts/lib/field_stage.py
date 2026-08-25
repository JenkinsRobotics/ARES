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
import queue
import signal
import socket
import subprocess
import sys
import threading
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



# ── earned budgets ──────────────────────────────────────────────────────
#
# A fixed deadline is wrong in both directions. Too generous and a hung
# stage burns the whole cap before reporting (the ARES controller suite
# spent 25 minutes to tell us nothing). Too tight and a legitimately slow
# stage can never go green, so nobody ever learns its real cost.
#
# So budgets are EARNED. A stage that has never passed runs against the
# floor — small, cheap to discover, fast to fail. Once it passes, its
# observed duration is recorded and its budget becomes that duration plus
# a margin, which is both more generous than the floor for genuinely slow
# work and far TIGHTER than a blanket cap for fast work: a stage that
# normally takes 7s gets ~20s, so a hang is caught in seconds, not
# minutes.
#
# The baseline is a committed file, not hidden local state. Budgets then
# move only through review, and a stage that suddenly needs twice as long
# shows up as a diff instead of silently absorbing the slack.
MARGIN = 2.0          # observed × MARGIN, so normal variance never flakes
GROWTH = 2.0          # how much one --grow retry may add
MIN_EARNED = 15.0     # absolute floor under an EARNED budget, so a
                      # sub-second stage still tolerates a cold cache


def load_baseline(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def resolve_budget(name: str, baseline: dict, floor: float,
                   ceiling: float) -> tuple[float, str]:
    """The budget this stage has earned, and why."""
    entry = baseline.get(name, {})
    seen = entry.get("seconds")
    if not isinstance(seen, (int, float)) or seen <= 0:
        # Never passed. If earlier runs timed out, RAMP rather than repeat
        # the same doomed budget forever: a stage that honestly needs 25
        # minutes can never record a passing duration if it is only ever
        # given five, so it would stay permanently unqualified. Each timeout
        # buys the next run a larger budget, bounded by the ceiling, so the
        # true cost is discovered in a few runs instead of guessed at once.
        # A stage that FAILS (rather than times out) never ramps — more time
        # does not fix a failing test.
        last = entry.get("timed_out_at")
        if isinstance(last, (int, float)) and last > 0:
            ramped = min(last * GROWTH, ceiling)
            return ramped, f"ramped ({last:.0f}s timed out, x{GROWTH:g})"
        return floor, "floor (never passed)"
    # NOTE: `floor` deliberately does not apply here. It is the budget for a
    # stage with no history, not a lower bound on earned ones — clamping to
    # it would hand a 6-second stage two minutes to hang in, which is the
    # slack this whole mechanism exists to remove.
    earned = min(max(seen * MARGIN, MIN_EARNED), ceiling)
    return earned, f"earned ({seen:.1f}s observed x{MARGIN:g})"


def record_baseline(path: Path, name: str, seconds: float) -> None:
    """Remember a PASSING duration. A pass clears any ramp history."""
    _write(path, name, {"seconds": round(seconds, 2)})


def record_timeout(path: Path, name: str, budget: float) -> None:
    """Remember that this budget was not enough, so the next run ramps."""
    data = load_baseline(path)
    if data.get(name, {}).get("seconds"):
        return          # already qualified; a one-off timeout is not new data
    _write(path, name, {"timed_out_at": round(budget, 2)})


def _write(path: Path, name: str, entry: dict) -> None:
    data = load_baseline(path)
    data[name] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(data.items())), indent=2) + "\n")


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

    # The reader runs on its own thread and the deadline is enforced HERE,
    # not on line boundaries. Checking the clock only after a line arrives
    # looks equivalent and is not: a process that goes silent — the actual
    # hang this harness exists to catch — never delivers another line, so a
    # blocking `for line in proc.stdout` would wait forever and the deadline
    # would never be evaluated at all.
    lines: "queue.Queue[str | None]" = queue.Queue()

    def _pump() -> None:
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                lines.put(raw)
        except Exception:
            pass
        finally:
            lines.put(None)

    reader = threading.Thread(target=_pump, name="field-stage-reader", daemon=True)
    reader.start()

    timed_out = False
    try:
        while True:
            remaining = timeout - (time.time() - started)
            if remaining <= 0:
                timed_out = True
                break
            try:
                line = lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue                          # tick the clock, keep waiting
            if line is None:
                break                             # stdout closed: process done
            sys.stdout.write(f"    │ {line}")
            sys.stdout.flush()
            if log:
                log.write(line)
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
    ap.add_argument("--timeout", type=float, default=None,
                    help="explicit budget; overrides the earned one")
    ap.add_argument("--floor", type=float, default=120.0,
                    help="budget for a stage that has never passed")
    ap.add_argument("--ceiling", type=float, default=900.0,
                    help="the most this stage may ever be given")
    ap.add_argument("--baseline", default=None,
                    help="committed JSON of observed passing durations")
    ap.add_argument("--grow", action="store_true",
                    help="on timeout, retry once with a larger budget")
    ap.add_argument("--log", default=None)
    ap.add_argument("--cwd", default=None)
    ap.add_argument("--report", default=None, help="append the record here as JSONL")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()

    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        print("no command given", file=sys.stderr)
        return 2

    base_path = Path(args.baseline) if args.baseline else None
    baseline = load_baseline(base_path) if base_path else {}

    if args.timeout is not None:
        budget, why = args.timeout, "explicit"
    else:
        budget, why = resolve_budget(args.name, baseline, args.floor, args.ceiling)
    print(f"    budget {budget:.0f}s — {why}")

    log = Path(args.log) if args.log else None
    rec = run_stage(args.name, cmd, budget, cwd=args.cwd, log_path=log)

    # One escalation, and only for a timeout: a stage that FAILED does not
    # deserve more time, it deserves a fix. Growth is capped by the ceiling
    # so a genuine hang still terminates.
    if rec["status"] == "timeout" and args.grow and budget < args.ceiling:
        grown = min(budget * GROWTH, args.ceiling)
        print(f"    timed out at {budget:.0f}s — retrying once at {grown:.0f}s")
        rec = run_stage(args.name, cmd, grown, cwd=args.cwd, log_path=log)
        rec["grown_from"] = budget

    rec["budget_s"] = rec.pop("timeout_s", None)
    rec["budget_source"] = why

    if base_path is not None:
        if rec["status"] == "pass":
            record_baseline(base_path, args.name, rec["seconds"])
        elif rec["status"] == "timeout":
            record_timeout(base_path, args.name, rec["budget_s"] or budget)
            print(f"    recorded timeout at {rec['budget_s']:.0f}s — "
                  "next run gets more")

    if args.report:
        with open(args.report, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    return 0 if rec["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
