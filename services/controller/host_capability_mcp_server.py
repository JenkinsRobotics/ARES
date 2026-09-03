"""Identity-scoped, audited host capabilities for independently owned agents.

Agentgateway starts one copy of this stdio server per identity.  The identity
and grants are fixed by the parent process, not supplied by an MCP caller.
There is deliberately no shell, delete, chmod, credential, or unrestricted
home-directory tool here. Host operations are typed and individually granted.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # MCP SDK 2.x renamed the server implementation.
    from mcp.server.mcpserver import MCPServer as FastMCP


MAX_BYTES = 1_000_000
IDENTITY = os.environ.get("ARES_CAPABILITY_IDENTITY", "").strip()
GRANTS_PATH = Path(
    os.environ.get("ARES_CAPABILITY_GRANTS")
    or Path.home() / ".ares" / "capabilities" / "grants.json"
)
AUDIT_PATH = Path(
    os.environ.get("ARES_CAPABILITY_AUDIT")
    or Path.home() / ".ares" / "audit" / "host-capabilities.jsonl"
)
ARES_SYSTEM_URL = os.environ.get("ARES_SYSTEM_URL", "http://127.0.0.1:8788").rstrip("/")
mcp = FastMCP(f"ares-host-{IDENTITY or 'invalid'}")


def _grant() -> dict[str, Any]:
    if IDENTITY not in {"admin", "hermes", "jaeger"}:
        raise PermissionError("host capability identity is missing or invalid")
    raw = json.loads(GRANTS_PATH.read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        raise RuntimeError("unsupported host-capability grant version")
    grant = (raw.get("identities") or {}).get(IDENTITY)
    if not isinstance(grant, dict):
        raise PermissionError(f"no host capability grant exists for {IDENTITY}")
    return grant


def _roots(grant: dict[str, Any] | None = None) -> list[Path]:
    value = grant or _grant()
    roots = [Path(str(item)).expanduser().resolve() for item in value.get("roots") or []]
    if not roots:
        raise PermissionError("identity has no workspace roots")
    return roots


def _require(capability: str) -> dict[str, Any]:
    grant = _grant()
    if capability not in set(grant.get("capabilities") or []):
        raise PermissionError(f"{IDENTITY} is not granted {capability}")
    return grant


def _resolve(path: str, *, must_exist: bool = True, capability: str = "") -> Path:
    grant = _grant()
    roots = _roots(grant)
    requested = str(path or "").strip()
    if not requested or requested == "/workspace":
        candidate = roots[0]
    elif requested.startswith("/workspace/"):
        candidate = roots[0] / requested.removeprefix("/workspace/")
    else:
        candidate = Path(requested).expanduser()
        if not candidate.is_absolute():
            candidate = roots[0] / candidate
    try:
        resolved = candidate.resolve(strict=must_exist)
        if not must_exist and not candidate.exists():
            resolved = candidate.parent.resolve(strict=True) / candidate.name
        if not any(resolved == root or root in resolved.parents for root in roots):
            raise PermissionError("path is outside this identity's approved workspace roots")
        return resolved
    except Exception as exc:
        if capability:
            _audit(
                capability, outcome="denied", requested_path=requested[:1024],
                error=type(exc).__name__,
            )
        raise


def _audit(capability: str, *, outcome: str, path: Path | None = None, **details: Any) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    AUDIT_PATH.parent.chmod(0o700)
    record = {
        "at": time.time(),
        "identity": IDENTITY,
        "capability": capability,
        "outcome": outcome,
        **({"path": str(path)} if path else {}),
        **details,
    }
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    fd = os.open(AUDIT_PATH, flags, 0o600)
    try:
        os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _system_request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{ARES_SYSTEM_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(1_000_001)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise PermissionError(f"ARES rejected the effect lease: HTTP {exc.code}: {detail}") from exc
    if len(raw) > 1_000_000:
        raise RuntimeError("ARES effect response exceeded the safety limit")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("ARES effect response is invalid")
    return value


def _effect_payload(capability: str, values: dict[str, Any]) -> tuple[str, bytes]:
    encoded = json.dumps(
        {"capability": capability, "values": values},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return _sha256(encoded), encoded


def _authorize_effect(
    capability: str,
    values: dict[str, Any],
    approval_id: str,
    *,
    reason: str,
    benefit: str,
    risks: list[str],
    scope: str,
    reversible: str,
    safer_alternative: str,
    data_destination: str,
) -> dict[str, Any] | None:
    """Request or consume a one-shot ARES lease for an exact typed action."""

    _require(capability)
    payload_sha256, _encoded = _effect_payload(capability, values)
    if not approval_id:
        request = _system_request("/api/effects/request", {
            "agent_id": IDENTITY,
            "capability": capability,
            "payload_sha256": payload_sha256,
            "operation": capability,
            "reason": reason,
            "benefit": benefit,
            "risks": risks,
            "scope": scope,
            "reversible": reversible,
            "safer_alternative": safer_alternative,
            "provider": "local-mac",
            "data_destination": data_destination,
        })
        _audit(capability, outcome="approval_required", approval_id=request.get("approval_id"))
        return request
    _system_request(f"/api/effects/{approval_id}/consume", {
        "agent_id": IDENTITY,
        "capability": capability,
        "payload_sha256": payload_sha256,
    })
    _audit(capability, outcome="approval_consumed", approval_id=approval_id)
    return None


def _run_jxa(source: str, values: dict[str, Any], *, timeout: int = 30) -> dict[str, Any]:
    """Run static JXA with all untrusted values isolated in one JSON argv."""

    completed = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", "-e", source, "--", json.dumps(values)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home())},
        check=False,
    )
    stdout = completed.stdout[:MAX_BYTES].strip()
    stderr = completed.stderr[:20_000].strip()
    data: Any = None
    if completed.returncode == 0 and stdout:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            data = stdout
    return {
        "exit_code": completed.returncode,
        "data": data,
        "error": stderr if completed.returncode else "",
    }


def _run_readonly(args: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
        check=False,
    )
    stdout = completed.stdout[:MAX_BYTES]
    stderr = completed.stderr[:20_000]
    return {"exit_code": completed.returncode, "stdout": stdout, "stderr": stderr}


@mcp.tool()
def capabilities_inspect() -> dict[str, Any]:
    """Show this caller's identity, approved roots, and granted capabilities."""

    grant = _grant()
    result = {
        "identity": IDENTITY,
        "roots": [str(root) for root in _roots(grant)],
        "capabilities": sorted(set(grant.get("capabilities") or [])),
        "limits": {"max_file_bytes": MAX_BYTES, "arbitrary_shell": False, "delete": False},
    }
    _audit("capabilities.inspect", outcome="allowed")
    return result


@mcp.tool()
def workspace_list(path: str = "/workspace") -> list[dict[str, Any]]:
    """List one approved workspace directory without reading file contents."""

    capability = "workspace.list"
    _require(capability)
    target = _resolve(path, capability=capability)
    try:
        if not target.is_dir():
            raise NotADirectoryError(str(target))
        rows = []
        for item in sorted(target.iterdir(), key=lambda value: value.name.lower())[:1000]:
            stat = item.lstat()
            rows.append({
                "name": item.name,
                "kind": "link" if item.is_symlink() else ("directory" if item.is_dir() else "file"),
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            })
        _audit(capability, outcome="allowed", path=target, entries=len(rows))
        return rows
    except Exception as exc:
        _audit(capability, outcome="denied", path=target, error=type(exc).__name__)
        raise


@mcp.tool()
def workspace_read(path: str) -> dict[str, Any]:
    """Read one UTF-8 text file under an approved root (maximum 1 MB)."""

    capability = "workspace.read"
    _require(capability)
    target = _resolve(path, capability=capability)
    try:
        if not target.is_file():
            raise FileNotFoundError(str(target))
        data = target.read_bytes()
        if len(data) > MAX_BYTES:
            raise ValueError("file exceeds the 1 MB host-capability limit")
        text = data.decode("utf-8")
        result = {"path": str(target), "content": text, "bytes": len(data), "sha256": _sha256(data)}
        _audit(capability, outcome="allowed", path=target, bytes=len(data), sha256=result["sha256"])
        return result
    except Exception as exc:
        _audit(capability, outcome="denied", path=target, error=type(exc).__name__)
        raise


@mcp.tool()
def workspace_write(path: str, content: str, expected_sha256: str = "") -> dict[str, Any]:
    """Atomically write UTF-8 text under an approved root.

    Existing files require their current SHA-256 in ``expected_sha256`` to
    prevent silent overwrites. New files require an empty precondition.
    """

    capability = "workspace.write"
    _require(capability)
    raw = content.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("content exceeds the 1 MB host-capability limit")
    target = _resolve(path, must_exist=False, capability=capability)
    try:
        target.parent.mkdir(parents=False, exist_ok=True)
        if target.exists():
            if not target.is_file():
                raise ValueError("target is not a regular file")
            current = target.read_bytes()
            current_hash = _sha256(current)
            if not expected_sha256 or expected_sha256 != current_hash:
                raise RuntimeError(f"write precondition failed; current sha256 is {current_hash}")
        elif expected_sha256:
            raise RuntimeError("write precondition failed; target does not exist")
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        result = {"path": str(target), "bytes": len(raw), "sha256": _sha256(raw)}
        _audit(capability, outcome="allowed", path=target, bytes=len(raw), sha256=result["sha256"])
        return result
    except Exception as exc:
        _audit(capability, outcome="denied", path=target, error=type(exc).__name__)
        raise


@mcp.tool()
def workspace_mkdir(path: str) -> dict[str, Any]:
    """Create one directory below an approved root; parents must exist."""

    capability = "workspace.mkdir"
    _require(capability)
    target = _resolve(path, must_exist=False, capability=capability)
    try:
        target.mkdir(parents=False, exist_ok=False, mode=0o700)
        _audit(capability, outcome="allowed", path=target)
        return {"path": str(target), "created": True}
    except Exception as exc:
        _audit(capability, outcome="denied", path=target, error=type(exc).__name__)
        raise


def _text(value: str, name: str, *, maximum: int, required: bool = True) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{name} is required")
    if "\x00" in result or len(result.encode("utf-8")) > maximum:
        raise ValueError(f"{name} is invalid or exceeds {maximum} bytes")
    return result


_CALENDAR_LIST_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Calendar');
  const start = new Date();
  const end = new Date(start.getTime() + o.days * 86400000);
  const rows = [];
  for (const calendar of app.calendars()) {
    for (const event of calendar.events()) {
      const eventStart = event.startDate();
      if (eventStart >= start && eventStart < end) {
        rows.push({id: String(event.uid()), calendar: String(calendar.name()), summary: String(event.summary()), start: eventStart.toISOString(), end: event.endDate().toISOString(), location: String(event.location() || '')});
        if (rows.length >= o.limit) return JSON.stringify(rows);
      }
    }
  }
  rows.sort((a, b) => a.start.localeCompare(b.start));
  return JSON.stringify(rows.slice(0, o.limit));
}
"""

_CALENDAR_CREATE_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Calendar');
  const calendars = app.calendars();
  const calendar = o.calendar ? calendars.find(c => String(c.name()) === o.calendar) : calendars[0];
  if (!calendar) throw new Error('Calendar not found');
  const event = app.Event({summary: o.summary, startDate: new Date(o.start), endDate: new Date(o.end), location: o.location, description: o.notes});
  calendar.events.push(event);
  return JSON.stringify({created: true, id: String(event.uid()), calendar: String(calendar.name())});
}
"""

_NOTES_LIST_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Notes');
  const rows = [];
  for (const account of app.accounts()) for (const folder of account.folders()) for (const note of folder.notes()) {
    rows.push({id: String(note.id()), title: String(note.name()), folder: String(folder.name()), modified: String(note.modificationDate())});
    if (rows.length >= o.limit) return JSON.stringify(rows);
  }
  return JSON.stringify(rows);
}
"""

_NOTES_READ_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Notes');
  for (const account of app.accounts()) for (const folder of account.folders()) for (const note of folder.notes()) {
    if (String(note.id()) === o.query || String(note.name()) === o.query) return JSON.stringify({id: String(note.id()), title: String(note.name()), folder: String(folder.name()), body: String(note.plaintext())});
  }
  throw new Error('Note not found');
}
"""

_NOTES_CREATE_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Notes');
  let folder = app.defaultAccount.folders()[0];
  if (o.folder) {
    for (const candidate of app.defaultAccount.folders()) if (String(candidate.name()) === o.folder) folder = candidate;
  }
  const note = app.Note({name: o.title, body: o.body});
  folder.notes.push(note);
  return JSON.stringify({created: true, id: String(note.id()), title: String(note.name()), folder: String(folder.name())});
}
"""

_REMINDERS_LIST_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Reminders');
  const rows = [];
  for (const list of app.lists()) {
    if (o.list && String(list.name()) !== o.list) continue;
    for (const reminder of list.reminders()) {
      if (!o.include_completed && Boolean(reminder.completed())) continue;
      rows.push({id: String(reminder.id()), name: String(reminder.name()), list: String(list.name()), completed: Boolean(reminder.completed()), due: reminder.dueDate() ? reminder.dueDate().toISOString() : ''});
      if (rows.length >= o.limit) return JSON.stringify(rows);
    }
  }
  return JSON.stringify(rows);
}
"""

_REMINDERS_CREATE_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Reminders');
  const lists = app.lists();
  const list = lists.find(candidate => String(candidate.name()) === o.list) || lists[0];
  if (!list) throw new Error('Reminder list not found');
  const properties = {name: o.name, body: o.notes};
  if (o.due) properties.dueDate = new Date(o.due);
  const reminder = app.Reminder(properties);
  list.reminders.push(reminder);
  return JSON.stringify({created: true, id: String(reminder.id()), list: String(list.name())});
}
"""


@mcp.tool()
def calendar_list(days: int = 7, limit: int = 100) -> dict[str, Any]:
    """List upcoming Apple Calendar events using a static, injection-safe JXA program."""

    capability = "calendar.list"
    _require(capability)
    values = {"days": max(1, min(int(days), 31)), "limit": max(1, min(int(limit), 500))}
    result = _run_jxa(_CALENDAR_LIST_JXA, values)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed", count=len(result.get("data") or []))
    return result


@mcp.tool()
def calendar_create(
    summary: str,
    start: str,
    end: str,
    calendar: str = "",
    location: str = "",
    notes: str = "",
    approval_id: str = "",
) -> dict[str, Any]:
    """Preview or create exactly one Calendar event after one-shot ARES approval."""

    values = {
        "summary": _text(summary, "summary", maximum=500),
        "start": _text(start, "start", maximum=64),
        "end": _text(end, "end", maximum=64),
        "calendar": _text(calendar, "calendar", maximum=250, required=False),
        "location": _text(location, "location", maximum=1000, required=False),
        "notes": _text(notes, "notes", maximum=20_000, required=False),
    }
    try:
        start_date = datetime.fromisoformat(values["start"].replace("Z", "+00:00"))
        end_date = datetime.fromisoformat(values["end"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("start and end must be ISO-8601 datetimes") from exc
    if end_date <= start_date:
        raise ValueError("end must be after start")
    pending = _authorize_effect(
        "calendar.create", values, approval_id,
        reason=f"Create Calendar event '{values['summary']}' from {values['start']} to {values['end']}",
        benefit="Records the requested event in Apple Calendar.",
        risks=["The event may sync to other devices or be visible to a shared calendar."],
        scope=f"One event titled '{values['summary']}' in {values['calendar'] or 'the default calendar'}.",
        reversible="Yes. Delete the created event from Calendar.",
        safer_alternative="Return this event as a draft without creating it.",
        data_destination="Apple Calendar and its configured sync account",
    )
    if pending:
        return pending
    result = _run_jxa(_CALENDAR_CREATE_JXA, values)
    _audit("calendar.create", outcome="allowed" if result["exit_code"] == 0 else "failed", approval_id=approval_id)
    return result


@mcp.tool()
def notes_list(limit: int = 50) -> dict[str, Any]:
    """List Apple Notes titles and metadata without returning note bodies."""

    capability = "notes.list"
    _require(capability)
    result = _run_jxa(_NOTES_LIST_JXA, {"limit": max(1, min(int(limit), 500))})
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed")
    return result


@mcp.tool()
def notes_read(query: str) -> dict[str, Any]:
    """Read one Apple Note by exact title or owner-issued id."""

    capability = "notes.read"
    _require(capability)
    result = _run_jxa(_NOTES_READ_JXA, {"query": _text(query, "query", maximum=1000)})
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed")
    return result


@mcp.tool()
def notes_create(title: str, body: str, folder: str = "", approval_id: str = "") -> dict[str, Any]:
    """Preview or create one Apple Note after one-shot ARES approval."""

    values = {
        "title": _text(title, "title", maximum=500),
        "body": _text(body, "body", maximum=100_000),
        "folder": _text(folder, "folder", maximum=500, required=False),
    }
    pending = _authorize_effect(
        "notes.create", values, approval_id,
        reason=f"Create Apple Note '{values['title']}'",
        benefit="Stores the requested text in Apple Notes.",
        risks=["The note contents may sync to iCloud and other signed-in devices."],
        scope=f"One note titled '{values['title']}' in {values['folder'] or 'the default folder'}.",
        reversible="Yes. Delete the created note; synced copies may remain in Recently Deleted temporarily.",
        safer_alternative="Save a draft under the approved workspace instead.",
        data_destination="Apple Notes and its configured sync account",
    )
    if pending:
        return pending
    result = _run_jxa(_NOTES_CREATE_JXA, values)
    _audit("notes.create", outcome="allowed" if result["exit_code"] == 0 else "failed", approval_id=approval_id)
    return result


@mcp.tool()
def reminders_list(list_name: str = "", include_completed: bool = False, limit: int = 100) -> dict[str, Any]:
    """List reminders from Apple Reminders."""

    capability = "reminders.list"
    _require(capability)
    values = {
        "list": _text(list_name, "list_name", maximum=500, required=False),
        "include_completed": bool(include_completed),
        "limit": max(1, min(int(limit), 500)),
    }
    result = _run_jxa(_REMINDERS_LIST_JXA, values)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed")
    return result


@mcp.tool()
def reminders_create(
    name: str,
    list_name: str = "Reminders",
    notes: str = "",
    due: str = "",
    approval_id: str = "",
) -> dict[str, Any]:
    """Preview or create one reminder after one-shot ARES approval."""

    values = {
        "name": _text(name, "name", maximum=500),
        "list": _text(list_name, "list_name", maximum=500),
        "notes": _text(notes, "notes", maximum=20_000, required=False),
        "due": _text(due, "due", maximum=64, required=False),
    }
    if values["due"]:
        try:
            datetime.fromisoformat(values["due"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("due must be an ISO-8601 datetime") from exc
    pending = _authorize_effect(
        "reminders.create", values, approval_id,
        reason=f"Create reminder '{values['name']}' in '{values['list']}'",
        benefit="Records the requested task in Apple Reminders.",
        risks=["The reminder may sync to shared lists or other devices."],
        scope=f"One reminder titled '{values['name']}' in list '{values['list']}'.",
        reversible="Yes. Delete or complete the reminder.",
        safer_alternative="Return a reminder draft without creating it.",
        data_destination="Apple Reminders and its configured sync account",
    )
    if pending:
        return pending
    result = _run_jxa(_REMINDERS_CREATE_JXA, values)
    _audit("reminders.create", outcome="allowed" if result["exit_code"] == 0 else "failed", approval_id=approval_id)
    return result


@mcp.tool()
def shortcuts_list() -> dict[str, Any]:
    """List installed Apple Shortcuts without running them."""

    capability = "shortcuts.list"
    _require(capability)
    result = _run_readonly(["/usr/bin/shortcuts", "list"])
    result["shortcuts"] = [line for line in result["stdout"].splitlines() if line.strip()][:1000]
    result.pop("stdout", None)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed")
    return result


@mcp.tool()
def shortcuts_run(name: str, input_text: str = "", approval_id: str = "") -> dict[str, Any]:
    """Preview or run one named Apple Shortcut after one-shot ARES approval."""

    values = {
        "name": _text(name, "name", maximum=500),
        "input": _text(input_text, "input_text", maximum=100_000, required=False),
    }
    pending = _authorize_effect(
        "shortcuts.run", values, approval_id,
        reason=f"Run Apple Shortcut '{values['name']}'",
        benefit="Runs the exact installed shortcut requested.",
        risks=["Shortcuts can perform external writes, network requests, messages, or device actions."],
        scope=f"One execution of the installed shortcut '{values['name']}'.",
        reversible="Depends on the shortcut; treat it as potentially irreversible.",
        safer_alternative="Inspect the shortcut in the Shortcuts app or deny this execution.",
        data_destination="Destinations configured inside the selected Apple Shortcut",
    )
    if pending:
        return pending
    args = ["/usr/bin/shortcuts", "run", values["name"]]
    completed = subprocess.run(
        args, input=values["input"] or None, capture_output=True, text=True,
        timeout=120, env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}, check=False,
    )
    result = {"exit_code": completed.returncode, "stdout": completed.stdout[:MAX_BYTES], "stderr": completed.stderr[:20_000]}
    _audit("shortcuts.run", outcome="allowed" if completed.returncode == 0 else "failed", approval_id=approval_id)
    return result


@mcp.tool()
def workspace_move(source: str, destination: str, approval_id: str = "") -> dict[str, Any]:
    """Preview or atomically move one item within approved roots."""

    capability = "workspace.move"
    source_path = _resolve(source, capability=capability)
    destination_path = _resolve(destination, must_exist=False, capability=capability)
    if destination_path.exists():
        raise FileExistsError(str(destination_path))
    values = {"source": str(source_path), "destination": str(destination_path)}
    pending = _authorize_effect(
        capability, values, approval_id,
        reason=f"Move '{source_path.name}' to '{destination_path}'",
        benefit="Moves or renames the requested workspace item.",
        risks=["References to the old path may break; synchronized folders may propagate the move."],
        scope=f"One item: {source_path} → {destination_path}",
        reversible="Usually yes by moving it back, unless another process changes the destination.",
        safer_alternative="Copy the item or leave it in place.",
        data_destination=str(destination_path.parent),
    )
    if pending:
        return pending
    os.replace(source_path, destination_path)
    _audit(capability, outcome="allowed", path=destination_path, approval_id=approval_id)
    return {"moved": True, "source": str(source_path), "destination": str(destination_path)}


def _git(path: str, args: list[str], capability: str) -> dict[str, Any]:
    _require(capability)
    target = _resolve(path, capability=capability)
    if target.is_file():
        target = target.parent
    command = [
        "/usr/bin/git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
        "-c", "diff.external=", "-c", "diff.trustExitCode=false", *args,
    ]
    result = _run_readonly(command, cwd=target)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed", path=target, exit_code=result["exit_code"])
    return result


@mcp.tool()
def git_status(path: str = "/workspace") -> dict[str, Any]:
    """Run a hook-disabled, read-only Git status in an approved workspace."""

    return _git(path, ["status", "--short", "--branch", "--untracked-files=normal"], "git.status")


@mcp.tool()
def git_diff(path: str = "/workspace") -> dict[str, Any]:
    """Read the working-tree Git diff without external diff drivers."""

    return _git(path, ["--no-pager", "diff", "--no-ext-diff", "--no-textconv"], "git.diff")


@mcp.tool()
def service_status() -> dict[str, Any]:
    """Probe the public health endpoints; this cannot start or stop services."""

    import urllib.error
    import urllib.request

    capability = "service.status"
    _require(capability)
    endpoints = {
        "ares": "http://127.0.0.1:8788/health",
        "jaeger": "http://127.0.0.1:8791/health",
        "ollama": "http://127.0.0.1:11434/api/tags",
        "n8n": "http://127.0.0.1:5678/healthz",
    }
    result: dict[str, Any] = {}
    for name, url in endpoints.items():
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                response.read(4096)
                result[name] = {"online": True, "http_status": response.status}
        except urllib.error.HTTPError as exc:
            result[name] = {"online": True, "http_status": exc.code}
        except Exception as exc:
            result[name] = {"online": False, "error": type(exc).__name__}
    _audit(capability, outcome="allowed")
    return result


# ── Camera & Physical Perception ──────────────────────────────────────────────

@mcp.tool()
def camera_status() -> dict[str, Any]:
    """Inspect the status and gimbal orientation of the connected camera."""
    capability = "camera.status"
    _require(capability)
    try:
        from integrations.hardware import get_hardware_adapter
        cam = get_hardware_adapter()
        info = cam.status()
        _audit(capability, outcome="allowed", info=info)
        return info
    except Exception as exc:
        _audit(capability, outcome="error", error=str(exc))
        raise


@mcp.tool()
def camera_snapshot(resolution: str = "1920x1080", approval_id: str = "") -> dict[str, Any]:
    """Capture a single frame from the camera to serve as visual input for the agent.

    Saves the image under the approved root workspace and returns path and dimensions.
    """
    capability = "camera.snapshot"
    if resolution not in {"640x480", "1280x720", "1920x1080", "3840x2160"}:
        raise ValueError("resolution is not an allowed capture size")
    values = {"resolution": resolution}
    pending = _authorize_effect(
        capability, values, approval_id,
        reason=f"Capture one camera frame at {resolution}",
        benefit="Provides one current image for the selected assistant task.",
        risks=["The frame may contain people, documents, screens, or other private surroundings."],
        scope=f"One still frame at {resolution}; no continuous recording.",
        reversible="The saved frame can be deleted, but any model inference already performed cannot be undone.",
        safer_alternative="Deny and attach a manually reviewed image instead.",
        data_destination="Approved workspace snapshot directory; model routing is governed separately",
    )
    if pending:
        return pending
    grant = _grant()
    roots = _roots(grant)
    target_dir = roots[0] / ".ares" / "snapshots"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"snapshot_{int(time.time()*1000)}.jpg"
    try:
        from integrations.hardware import get_hardware_adapter
        cam = get_hardware_adapter()
        frame = cam.capture_frame(output_path=target_file, resolution=resolution)
        result = {
            "path": str(frame.path),
            "width": frame.width,
            "height": frame.height,
            "format": frame.format,
            "timestamp": frame.timestamp,
        }
        _audit(capability, outcome="allowed", path=frame.path)
        return result
    except Exception as exc:
        _audit(capability, outcome="error", error=str(exc))
        raise


@mcp.tool()
def camera_listen(duration_seconds: float = 3.0, approval_id: str = "") -> dict[str, Any]:
    """Record an audio clip from the camera beamforming microphone for speech/sound analysis."""
    capability = "camera.listen"
    duration = max(0.5, min(float(duration_seconds), 30.0))
    values = {"duration_seconds": duration}
    pending = _authorize_effect(
        capability, values, approval_id,
        reason=f"Record {duration:g} seconds from the camera microphone",
        benefit="Provides a short, bounded audio sample for the selected assistant task.",
        risks=["The clip may capture private speech or background sounds from nearby people."],
        scope=f"One audio clip lasting {duration:g} seconds; no background listening.",
        reversible="The saved clip can be deleted, but any model inference already performed cannot be undone.",
        safer_alternative="Deny and provide a typed message or manually reviewed recording.",
        data_destination="Approved workspace audio directory; model routing is governed separately",
    )
    if pending:
        return pending
    grant = _grant()
    roots = _roots(grant)
    target_dir = roots[0] / ".ares" / "audio"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"audio_{int(time.time()*1000)}.wav"
    try:
        from integrations.hardware import get_hardware_adapter
        cam = get_hardware_adapter()
        sample = cam.record_sample(duration_seconds=duration, output_path=target_file)
        result = {
            "path": str(sample.path),
            "duration_seconds": sample.duration_seconds,
            "sample_rate": sample.sample_rate,
            "timestamp": sample.timestamp,
        }
        _audit(capability, outcome="allowed", path=sample.path)
        return result
    except Exception as exc:
        _audit(capability, outcome="error", error=str(exc))
        raise


@mcp.tool()
def camera_ptz(action: str = "status", pan: int = 0, tilt: int = 0, approval_id: str = "") -> dict[str, Any]:
    """Control the camera motorized gimbal: 'center', 'deskview', 'aim', or 'status'."""
    capability = "camera.ptz"
    _require(capability)
    if action not in {"center", "deskview", "aim", "status"}:
        raise ValueError("camera action must be center, deskview, aim, or status")
    if not -180 <= int(pan) <= 180 or not -90 <= int(tilt) <= 90:
        raise ValueError("camera pan/tilt is outside the bounded range")
    if action != "status":
        values = {"action": action, "pan": int(pan), "tilt": int(tilt)}
        pending = _authorize_effect(
            capability, values, approval_id,
            reason=f"Move the camera gimbal using action '{action}'",
            benefit="Aims the camera for the requested visual task.",
            risks=["The camera may point toward people, screens, or private surroundings."],
            scope=f"One gimbal movement: {action} (pan {int(pan)}, tilt {int(tilt)}).",
            reversible="Yes. Center or reposition the gimbal.",
            safer_alternative="Deny and position the camera manually.",
            data_destination="Physical Insta360 camera gimbal",
        )
        if pending:
            return pending
    try:
        from integrations.hardware import get_hardware_adapter
        cam = get_hardware_adapter()
        if action == "center":
            pos = cam.center()
        elif action == "deskview":
            pos = cam.deskview()
        elif action == "aim":
            pos = cam.aim(pan=pan, tilt=tilt)
        else:
            pos = cam.get_position()
        result = {"action": action, "pan": pos.pan, "tilt": pos.tilt}
        _audit(capability, outcome="allowed", result=result)
        return result
    except Exception as exc:
        _audit(capability, outcome="error", error=str(exc))
        raise



# --- Knowledge Base tools ---
try:
    import sys as _sys, os as _os
    _ctrl_dir = _os.path.dirname(_os.path.abspath(__file__))
    if _ctrl_dir not in _sys.path:
        _sys.path.insert(0, _ctrl_dir)
    from core.knowledge.tools import register_all_kb_tools
    register_all_kb_tools(mcp, _require, _audit, _resolve)
except Exception as _kb_exc:
    import logging
    logging.getLogger(__name__).warning("Knowledge base tools not registered: %s", _kb_exc)



if __name__ == "__main__":
    mcp.run()
