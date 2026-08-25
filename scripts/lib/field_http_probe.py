"""Stage 05 — the controller boots, answers, and shuts down on a spare port.

Runs a REAL uvicorn against ``fastapi_app.main:app`` on the isolated port
the harness allocated, never the production 8788. Each phase is bounded
separately: "never came up", "came up but never answered" and "answered
but never died" are three different bugs and must not collapse into one
timeout.

Shutdown is checked as carefully as startup. A controller that ignores
SIGTERM is a release blocker in its own right — it turns every restart
into a port conflict, which is the shape of the stale-state failures the
recovery matrix cares about.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

BOOT_DEADLINE = 90.0
RESPONSE_DEADLINE = 15.0
SIGTERM_DEADLINE = 20.0

fails: list[str] = []


def check(ok: bool, msg: str) -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
    if not ok:
        fails.append(msg)
    return ok


def get(url: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read(2048)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return None, b""


def main() -> int:
    port = os.environ.get("ARES_WEBUI_PORT", "")
    if not port or port == "8788":
        print(f"refusing to run against port {port!r} — harness must allocate one")
        return 2
    base = f"http://127.0.0.1:{port}"

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "fastapi_app.main:app",
         "--host", "127.0.0.1", "--port", port, "--log-level", "warning"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    try:
        # 1. Boot — poll rather than sleep, so a fast boot is not punished.
        t0 = time.time()
        up = False
        while time.time() - t0 < BOOT_DEADLINE:
            if proc.poll() is not None:
                check(False, f"controller exited during boot (rc={proc.returncode})")
                return 1
            code, _ = get(f"{base}/api/health", timeout=3.0)
            if code is not None:
                up = True
                break
            time.sleep(0.5)
        if not check(up, f"controller answered within {BOOT_DEADLINE}s "
                         f"({time.time() - t0:.1f}s)"):
            return 1

        # 2. Health is a real 200, not merely "something listened".
        t1 = time.time()
        code, body = get(f"{base}/api/health", timeout=RESPONSE_DEADLINE)
        check(code == 200, f"/api/health returned 200 (got {code}, "
                           f"{time.time() - t1:.2f}s)")

        # 3. The SPA is actually mounted — apps/web/static is production.
        code, _ = get(f"{base}/", timeout=RESPONSE_DEADLINE)
        check(code in (200, 304), f"/ serves the frontend (got {code})")

        # 4. Orderly shutdown on SIGTERM, within a stated deadline.
        t2 = time.time()
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            proc.wait(timeout=SIGTERM_DEADLINE)
            check(True, f"exited on SIGTERM within {SIGTERM_DEADLINE}s "
                        f"({time.time() - t2:.2f}s)")
        except subprocess.TimeoutExpired:
            check(False, f"ignored SIGTERM for {SIGTERM_DEADLINE}s")

        # 5. The port is genuinely released, not held by a straggler.
        time.sleep(1.0)
        code, _ = get(f"{base}/api/health", timeout=3.0)
        check(code is None, "port released after shutdown")

    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)

    print(f"\n  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
