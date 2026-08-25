"""Stage 04 — a real bridge subprocess, driven to a clean exit under deadlines.

Not a unit test: this spawns ``python -m jaeger_ai.interfaces.bridge`` the
way the desktop app does, speaks NDJSON to it over stdio, and holds every
phase to its own deadline. That is the only way to catch the class of bug
where a phase never completes and the client waits forever — the field
symptom behind "ARES attaches and hangs".

It runs against the ISOLATED JAEGER_INSTANCE_DIR the harness exported, so
the instance deliberately does not exist. That is a documented, fully
specified path (fatal kind=no_instance, transport stays alive for
onboarding queries) and it exercises boot, query, quit and teardown
WITHOUT loading a multi-GB model — which is what keeps this stage a
90-second gate instead of a 15-minute one.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time

# Per-phase deadlines. Each is a separate number because each has a
# separate failure mode; one global timeout cannot tell "never booted"
# from "booted but never shut down".
READY_DEADLINE = 30.0
QUERY_DEADLINE = 20.0
QUIT_DEADLINE = 30.0
ATTACH_DEADLINE = 20.0
REAP_DEADLINE = 10.0

fails: list[str] = []


def check(ok: bool, msg: str) -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
    if not ok:
        fails.append(msg)
    return ok


def _stdout_frames(proc) -> "queue.Queue[str | None]":
    """Pump stdout off-thread so a silent child cannot defeat a deadline."""
    frames: "queue.Queue[str | None]" = queue.Queue()

    def pump() -> None:
        try:
            for line in proc.stdout:
                frames.put(line)
        finally:
            frames.put(None)

    threading.Thread(target=pump, name="field-bridge-reader", daemon=True).start()
    return frames


def read_frame(proc, frames, deadline: float, want: str | None = None):
    """Next NDJSON frame, or None if the deadline passes.

    Reads with a hard wall-clock bound: a bridge that stops emitting is the
    exact failure this stage exists to detect, so a blocking readline with
    no bound would hang the harness instead of reporting.
    """
    end = time.monotonic() + deadline
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return None
        try:
            line = frames.get(timeout=remaining)
        except queue.Empty:
            return None
        if line is None:
            return None
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            continue                     # stray non-protocol output on stdout
        if want is None or frame.get("type") == want:
            return frame
    return None



def main() -> int:
    inst = os.environ.get("JAEGER_INSTANCE_DIR", "")
    if not inst:
        print("JAEGER_INSTANCE_DIR unset — refusing to touch a real instance")
        return 2

    t0 = time.time()
    proc = subprocess.Popen(
        [sys.executable, "-m", "jaeger_ai.interfaces.bridge"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1, start_new_session=True,
    )
    frames = _stdout_frames(proc)

    try:
        # 1. FAST READY — the transport must be usable before the agent boots.
        ready = read_frame(proc, frames, READY_DEADLINE, want="ready")
        check(ready is not None,
              f"ready frame within {READY_DEADLINE}s "
              f"({time.time() - t0:.2f}s)")
        if ready is None:
            return 1

        # 2. Queries must work pre-instance — this is what onboarding runs on.
        proc.stdin.write(json.dumps(
            {"op": "query", "id": "q1", "what": "instance_exists"}) + "\n")
        proc.stdin.flush()
        t1 = time.time()
        res = read_frame(proc, frames, QUERY_DEADLINE, want="result")
        check(res is not None,
              f"query answered within {QUERY_DEADLINE}s ({time.time() - t1:.2f}s)")
        if res is not None:
            check(res.get("id") == "q1", "result carries the request id")

        # 3. ATTACH POINT — asserted ABSENT, deliberately.
        #
        # bridge.py's _publish_attach_socket returns early when
        # ``ctx.client is None``: with no agent there is nothing to attach
        # TO, so publishing the socket would let ARES connect to a bridge
        # that can never answer a turn — a hang that looks like a live
        # connection. This scenario has no instance, so the contract under
        # test is that the socket stays unpublished.
        #
        # Live attach (connect, ready frame, query round-trip) needs a
        # BOOTED agent and therefore a real model, so it belongs to stage
        # 06, not here. Asserting it in this stage would either fail
        # forever or tempt someone to publish the socket unconditionally.
        sock_path = os.path.join(inst, "run", "bridge.sock")
        time.sleep(1.0)
        check(not os.path.exists(sock_path),
              "attach point stays unpublished when no agent booted")

        # macOS caps AF_UNIX at 104 bytes. A longer path makes the bridge log
        # "attach socket skipped" and silently stop covering attach at all, so
        # the harness must verify its OWN paths are bindable — production is
        # 79 bytes; only a badly-chosen temp dir puts this at risk.
        check(len(sock_path) < 104,
              f"harness socket path is bindable ({len(sock_path)} < 104 bytes)")

        # 4. Orderly shutdown: bye, then the process actually goes away.
        proc.stdin.write(json.dumps({"op": "quit"}) + "\n")
        proc.stdin.flush()
        t2 = time.time()
        bye = read_frame(proc, frames, QUIT_DEADLINE, want="bye")
        check(bye is not None,
              f"bye frame within {QUIT_DEADLINE}s ({time.time() - t2:.2f}s)")

        try:
            proc.wait(timeout=REAP_DEADLINE)
            check(True, f"process exited within {REAP_DEADLINE}s of bye")
        except subprocess.TimeoutExpired:
            check(False, f"process still alive {REAP_DEADLINE}s after bye")

        # 5. No stragglers. A leaked process group poisons every later stage.
        try:
            os.killpg(os.getpgid(proc.pid), 0)
            leaked = True
        except (ProcessLookupError, PermissionError):
            leaked = False
        check(not leaked, "no leaked process group")

    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)

    print(f"\n  {len(fails)} failure(s) in {time.time() - t0:.2f}s")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
