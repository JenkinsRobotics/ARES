#!/usr/bin/env python3
"""Terminal client for production ARES chat and local private utilities."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parents[1]
ROOT = CONTROLLER.parents[1]
sys.path.insert(0, str(CONTROLLER))


def _base() -> str:
    host = os.environ.get("ARES_WEBUI_HOST", "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{os.environ.get('ARES_WEBUI_PORT', '8788')}"


def _request(path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        _base() + path, data=data,
        headers={"Accept": "application/json", **({"Content-Type": "application/json"} if data else {})},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise SystemExit(f"ARES API returned HTTP {exc.code}: {body}") from exc
    except OSError as exc:
        raise SystemExit(f"ARES service is unavailable at {_base()}: {exc}") from exc


def _chat(args) -> int:
    session_id = args.session
    workspace = str(Path(args.workspace or ROOT).expanduser().resolve())
    if not session_id:
        created = _request("/api/session/new", {
            "workspace": workspace, "profile": args.profile,
            "worktree": False, "source": "cli",
        })
        session_id = str(created["session"]["session_id"])
    started = _request("/api/sam-conversation/chat", {
        "session_id": session_id, "message": args.message,
        "workspace": workspace, "profile": args.profile,
        "explicit_model_pick": False,
    })
    stream_id = str(started["stream_id"])
    print(f"ARES session {session_id} · stream {stream_id}", file=sys.stderr)
    trace_handle = None
    if args.trace_file:
        trace_path = Path(args.trace_file).expanduser().resolve()
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_handle = trace_path.open("a", encoding="utf-8")
        trace_path.chmod(0o600)
        trace_handle.write(json.dumps({
            "event": "trace_start", "session_id": session_id,
            "stream_id": stream_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }) + "\n")
        trace_handle.flush()
    url = _base() + "/api/chat/stream?" + urllib.parse.urlencode({"stream_id": stream_id})
    request = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    event = "message"
    data_lines: list[str] = []
    try:
        with urllib.request.urlopen(request, timeout=max(30, args.timeout)) as response:
            while True:
                raw = response.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("event: "):
                    event = line[7:].strip()
                elif line.startswith("data: "):
                    data_lines.append(line[6:])
                elif line == "" and data_lines:
                    try:
                        payload = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError:
                        payload = {"text": "\n".join(data_lines)}
                    if trace_handle is not None:
                        trace_handle.write(json.dumps({
                            "event": event, "payload": payload,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }, ensure_ascii=False) + "\n")
                        trace_handle.flush()
                    if event == "token":
                        print(str(payload.get("text") or payload.get("delta") or ""), end="", flush=True)
                    elif event == "tool":
                        state = str(payload.get("event_type") or "tool")
                        print(f"\n[{state}: {payload.get('name') or 'unknown'}]", file=sys.stderr)
                    elif event == "reasoning":
                        # The full provider trace is available only in the
                        # explicitly requested mode-0600 audit file.
                        pass
                    elif event in {"apperror", "error", "cancel"}:
                        print(f"\nARES error: {payload.get('message') or payload}", file=sys.stderr)
                    elif event == "stream_end":
                        print()
                        if trace_handle is not None:
                            trace_handle.close()
                        return 0
                    event, data_lines = "message", []
    except (TimeoutError, urllib.error.URLError) as exc:
        raise SystemExit(f"ARES stream failed: {exc}") from exc
    finally:
        if trace_handle is not None and not trace_handle.closed:
            trace_handle.close()
    return 0


def _print_review(proposal: dict) -> None:
    print(f"Proposal: {proposal['proposal_id']}  Status: {proposal['status']}")
    print(f"Bookmarks: {proposal['bookmark_count']}  Folders: {proposal['folder_count']}")
    print(f"Same-folder duplicates proposed for removal: {proposal['duplicate_removal_count']}")
    print(f"Malformed/non-web URLs (report only): {proposal['malformed_count']}")
    print(f"Empty folders (report only): {proposal['empty_folder_count']}")
    for group in proposal.get("duplicate_groups", []):
        if len(group) < 2:
            continue
        print(f"\nDuplicate in {group[0]['folder']}:")
        for index, item in enumerate(group):
            action = "KEEP" if index == 0 else "REMOVE"
            print(f"  {action:6} {item['title']} — {item['url']}")


def _bookmarks(args) -> int:
    from api.safari_bookmarks import (
        SafariBookmarkError, apply_organization_proposal, apply_proposal, apply_recovery_proposal,
        create_organization_proposal, create_proposal, create_recovery_proposal, load_proposal,
        public_summary, rollback_proposal, verify_proposal,
    )
    try:
        if args.bookmark_command == "audit":
            proposal = create_proposal()
            _print_review(proposal)
            print("\nNo bookmarks were changed.")
            print(f"Approval token: {proposal['approval_token']}")
            print(f"Apply only after review: ares bookmarks apply {proposal['proposal_id']} --approve-token '{proposal['approval_token']}'")
        elif args.bookmark_command == "review":
            proposal = load_proposal(args.proposal_id)
            _print_review(proposal)
            if proposal.get("status") == "awaiting_approval":
                print(f"\nApproval token: {proposal['approval_token']}")
                print(f"Apply only after review: ares bookmarks apply {proposal['proposal_id']} --approve-token '{proposal['approval_token']}'")
        elif args.bookmark_command == "summary":
            proposal = create_proposal()
            print(json.dumps({
                "privacy": "aggregate only; no bookmark titles or URLs",
                "proposal": public_summary(proposal), "approval_required": True,
            }, indent=2))
        elif args.bookmark_command == "apply":
            print(json.dumps(apply_proposal(args.proposal_id, args.approve_token), indent=2))
        elif args.bookmark_command == "rollback":
            print(json.dumps(rollback_proposal(args.proposal_id, args.approve_token), indent=2))
        elif args.bookmark_command == "verify":
            print(json.dumps(verify_proposal(args.proposal_id), indent=2))
        elif args.bookmark_command == "recovery-plan":
            proposal = create_recovery_proposal(Path(args.restore_from))
            print(json.dumps({
                "proposal": public_summary(proposal),
                "approval_token": proposal["approval_token"],
                "warning": "Exact restore only; no bookmarks changed. Quit Safari before recover.",
            }, indent=2))
        elif args.bookmark_command == "recover":
            print(json.dumps(apply_recovery_proposal(args.proposal_id, args.approve_token), indent=2))
        elif args.bookmark_command == "organization-plan":
            proposal = create_organization_proposal()
            print(json.dumps({"proposal": public_summary(proposal), "approval_token": proposal["approval_token"]}, indent=2))
        elif args.bookmark_command == "organize":
            print(json.dumps(apply_organization_proposal(args.proposal_id, args.approve_token), indent=2))
    except SafariBookmarkError as exc:
        raise SystemExit(f"Safari bookmarks: {exc}") from exc
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="ares")
    sub = parser.add_subparsers(dest="command", required=True)
    chat = sub.add_parser("chat", help="send one turn through production ARES HTTP/SSE")
    chat.add_argument("message")
    chat.add_argument("--session")
    chat.add_argument("--workspace")
    chat.add_argument("--profile", default="default")
    chat.add_argument("--timeout", type=int, default=180)
    chat.add_argument("--trace-file", help="append complete SSE events to a mode-0600 NDJSON audit file")
    chat.set_defaults(handler=_chat)
    bookmarks = sub.add_parser("bookmarks", help="local privacy-preserving Safari bookmark operations")
    bookmark_sub = bookmarks.add_subparsers(dest="bookmark_command", required=True)
    for name in ("audit", "summary"):
        command = bookmark_sub.add_parser(name)
        command.set_defaults(handler=_bookmarks)
    review = bookmark_sub.add_parser("review")
    review.add_argument("proposal_id")
    review.set_defaults(handler=_bookmarks)
    apply_cmd = bookmark_sub.add_parser("apply")
    apply_cmd.add_argument("proposal_id")
    apply_cmd.add_argument("--approve-token", required=True)
    apply_cmd.set_defaults(handler=_bookmarks)
    rollback = bookmark_sub.add_parser("rollback")
    rollback.add_argument("proposal_id")
    rollback.add_argument("--approve-token", required=True)
    rollback.set_defaults(handler=_bookmarks)
    verify = bookmark_sub.add_parser("verify")
    verify.add_argument("proposal_id")
    verify.set_defaults(handler=_bookmarks)
    recovery = bookmark_sub.add_parser("recovery-plan")
    recovery.add_argument("restore_from")
    recovery.set_defaults(handler=_bookmarks)
    recover = bookmark_sub.add_parser("recover")
    recover.add_argument("proposal_id")
    recover.add_argument("--approve-token", required=True)
    recover.set_defaults(handler=_bookmarks)
    organize_plan = bookmark_sub.add_parser("organization-plan")
    organize_plan.set_defaults(handler=_bookmarks)
    organize = bookmark_sub.add_parser("organize")
    organize.add_argument("proposal_id")
    organize.add_argument("--approve-token", required=True)
    organize.set_defaults(handler=_bookmarks)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
