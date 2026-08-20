#!/usr/bin/env python3
"""Autonomous heartbeat tick for a single anchor ARES session.

Posts one prompt into ONE persistent session via the same endpoint the WebUI
composer uses (``POST /api/chat/start``), so the tick is indistinguishable from
the operator typing: same transcript, same bridge continuity key, same memory,
and the sidebar/SSE surfaces update for free.

Why not a cron schedule: ARES deliberately quarantines schedule runs into their
own ``cron_<job_id>_*`` sessions, bucketed under a separate cron project and
hidden from the sidebar by default (``show_cron_sessions``). Those defaults exist
to keep automation out of your chat -- which is the opposite of an anchor session.

Quiet by default: the Kanban board is polled first, and when nothing is
actionable the run exits WITHOUT writing to the session. That gate is what keeps
a 15-minute cadence from burying the anchor timeline in heartbeat prompts.

Usage:
    ARES_ANCHOR_SESSION=<session_id> heartbeat.py
    heartbeat.py --session <session_id> --dry-run

Exit codes: 0 = posted or intentionally idle, 1 = configuration/HTTP failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_PROMPT = """[HEARTBEAT]
Autonomous cycle in your persistent session.
1. Read the Kanban board and pick the single highest-priority actionable task
   (status 'ready', else 'todo').
2. Move it to 'running', do the work with your tools, then move it to 'done'
   -- or 'blocked' with a one-line reason if you need me.
3. Reply with a two-line summary: what changed, and what is next.
Do not re-plan work already captured on the board."""

# Statuses that represent work the agent may pick up unprompted.
ACTIONABLE = ("ready", "todo")
COOKIE_NAME = "ares_session"
CSRF_HEADER = "X-Ares-CSRF-Token"


class HeartbeatError(RuntimeError):
    pass


def _base_url(explicit: str | None) -> str:
    if explicit:
        return explicit.rstrip("/")
    env = os.getenv("ARES_BASE_URL")
    if env:
        return env.rstrip("/")
    return f"http://127.0.0.1:{os.getenv('ARES_WEBUI_PORT', '8788')}"


def _request(url: str, *, method: str = "GET", body: dict | None = None,
             token: str | None = None, csrf: str | None = None, timeout: float = 30.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Cookie", f"{COOKIE_NAME}={token}")
        # require_mutation_identity enforces CSRF only when auth is enabled;
        # sending it unconditionally alongside the cookie is harmless.
        req.add_header(CSRF_HEADER, csrf or token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise HeartbeatError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HeartbeatError(f"{method} {url} unreachable: {exc.reason}") from exc
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HeartbeatError(f"{method} {url} returned non-JSON: {raw[:200]}") from exc


def actionable_count(base: str, token: str | None, csrf: str | None) -> int:
    """Count board tasks the agent may act on without being asked."""
    stats = _request(f"{base}/api/kanban/stats", token=token, csrf=csrf)
    by_status = stats.get("by_status") or {}
    if not isinstance(by_status, dict):
        return 0
    total = 0
    for status in ACTIONABLE:
        try:
            total += int(by_status.get(status) or 0)
        except (TypeError, ValueError):
            continue
    return total


def session_is_busy(base: str, session_id: str, token: str | None, csrf: str | None) -> bool:
    """True while the anchor session already has a turn in flight.

    Without this a slow task stacks ticks on top of each other, which is how an
    anchor session turns into an unreadable pile of interleaved turns.
    """
    url = f"{base}/api/session?session_id={urllib.parse.quote(session_id)}&messages=0&resolve_model=0"
    payload = _request(url, token=token, csrf=csrf)
    session = payload.get("session")
    if not isinstance(session, dict):
        raise HeartbeatError(f"anchor session not found: {session_id}")
    if session.get("is_streaming"):
        return True
    return bool(session.get("active_stream_id"))


def post_tick(base: str, session_id: str, prompt: str, token: str | None, csrf: str | None) -> str:
    payload = _request(
        f"{base}/api/chat/start",
        method="POST",
        body={"session_id": session_id, "message": prompt},
        token=token,
        csrf=csrf,
    )
    return str(payload.get("stream_id") or "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Post one heartbeat tick into an anchor ARES session.")
    parser.add_argument("--session", default=os.getenv("ARES_ANCHOR_SESSION"),
                        help="anchor session_id (env: ARES_ANCHOR_SESSION)")
    parser.add_argument("--base-url", default=None,
                        help="ARES base URL (env: ARES_BASE_URL, default http://127.0.0.1:$ARES_WEBUI_PORT)")
    parser.add_argument("--prompt-file", default=os.getenv("ARES_HEARTBEAT_PROMPT_FILE"),
                        help="file holding the heartbeat prompt (env: ARES_HEARTBEAT_PROMPT_FILE)")
    parser.add_argument("--always", action="store_true",
                        help="post even when the board has no actionable task")
    parser.add_argument("--dry-run", action="store_true",
                        help="run every check and report, but never post")
    args = parser.parse_args(argv)

    if not args.session:
        print("heartbeat: no anchor session (--session or ARES_ANCHOR_SESSION)", file=sys.stderr)
        return 1

    base = _base_url(args.base_url)
    token = os.getenv("ARES_AUTH_TOKEN") or None
    csrf = os.getenv("ARES_CSRF_TOKEN") or None

    prompt = DEFAULT_PROMPT
    if args.prompt_file:
        try:
            prompt = open(args.prompt_file, encoding="utf-8").read().strip()
        except OSError as exc:
            print(f"heartbeat: cannot read prompt file: {exc}", file=sys.stderr)
            return 1
    if not prompt:
        print("heartbeat: prompt is empty", file=sys.stderr)
        return 1

    try:
        if not args.always:
            pending = actionable_count(base, token, csrf)
            if pending == 0:
                print("heartbeat: board is clear; staying quiet")
                return 0
            print(f"heartbeat: {pending} actionable task(s)")
        if session_is_busy(base, args.session, token, csrf):
            print("heartbeat: anchor session already streaming; skipping this tick")
            return 0
        if args.dry_run:
            print(f"heartbeat: dry-run, would post {len(prompt)} chars to {args.session}")
            return 0
        stream_id = post_tick(base, args.session, prompt, token, csrf)
        print(f"heartbeat: posted to {args.session}" + (f" (stream {stream_id})" if stream_id else ""))
        return 0
    except HeartbeatError as exc:
        print(f"heartbeat: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
