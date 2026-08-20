"""ARES-owned durable Kanban storage and delegation-backed dispatch.

The WebUI previously depended on an optional ``ares_cli.kanban_db`` package
that was not shipped by this repository.  This module is intentionally small:
it owns board/task persistence and delegates execution through ARES's existing
backend router instead of embedding another agent/worker implementation.
"""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
from typing import Any, Iterable, Iterator
import uuid


DEFAULT_BOARD = "default"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SCHEMA_LOCK = threading.RLock()


@dataclass
class Task:
    id: str
    title: str
    body: str | None
    status: str
    assignee: str | None
    created_by: str | None
    tenant: str | None
    priority: int
    workspace_kind: str | None
    workspace_path: str | None
    max_runtime_seconds: int | None
    skills: list[str]
    result: str | None
    summary: str | None
    block_reason: str | None
    created_at: int
    updated_at: int


@dataclass
class Comment:
    id: int
    task_id: str
    author: str
    body: str
    created_at: int


@dataclass
class Event:
    id: int
    task_id: str
    run_id: str | None
    kind: str
    payload: dict[str, Any] | None
    created_at: int


@dataclass
class Run:
    id: str
    task_id: str
    delegation_id: str | None
    status: str
    result: str | None
    error: str | None
    started_at: int
    finished_at: int | None


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT,
  status TEXT NOT NULL DEFAULT 'ready',
  assignee TEXT,
  created_by TEXT,
  tenant TEXT,
  priority INTEGER NOT NULL DEFAULT 0,
  workspace_kind TEXT,
  workspace_path TEXT,
  idempotency_key TEXT UNIQUE,
  max_runtime_seconds INTEGER,
  skills TEXT NOT NULL DEFAULT '[]',
  result TEXT,
  summary TEXT,
  block_reason TEXT,
  claim_lock TEXT,
  claim_expires INTEGER,
  worker_pid INTEGER,
  current_run_id TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS task_links (
  parent_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  child_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  PRIMARY KEY(parent_id, child_id),
  CHECK(parent_id != child_id)
);
CREATE TABLE IF NOT EXISTS task_comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  author TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  run_id TEXT,
  kind TEXT NOT NULL,
  payload TEXT,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS task_runs (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  delegation_id TEXT,
  status TEXT NOT NULL,
  result TEXT,
  error TEXT,
  started_at INTEGER NOT NULL,
  finished_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_events_id ON task_events(id);
"""


def _home() -> Path:
    root = (
        Path(os.environ.get("ARES_HOME", "~/.ares")).expanduser().resolve(strict=False)
    )
    return root / "kanban"


def _normalize_board_slug(slug: str | None) -> str | None:
    if slug is None or not str(slug).strip():
        return None
    value = str(slug).strip().lower().replace(" ", "-")
    if not _SLUG.fullmatch(value):
        raise ValueError(f"invalid board slug: {slug!r}")
    return value


def _board_slug(board: str | None = None) -> str:
    explicit = _normalize_board_slug(board)
    return explicit or get_current_board()


def _board_dir(board: str | None = None) -> Path:
    return _home() / "boards" / _board_slug(board)


def _db_path(board: str | None = None) -> Path:
    return _board_dir(board) / "kanban.db"


def _metadata_path(board: str | None = None) -> Path:
    return _board_dir(board) / "board.json"


def _current_path() -> Path:
    return _home() / "current"


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def get_current_board() -> str:
    try:
        value = _normalize_board_slug(
            _current_path().read_text(encoding="utf-8").strip()
        )
    except (OSError, ValueError):
        value = None
    return value or DEFAULT_BOARD


def set_current_board(slug: str) -> Path:
    value = _normalize_board_slug(slug)
    if not value or not board_exists(value):
        raise ValueError(f"board {slug!r} does not exist")
    _secure_directory(_home())
    path = _current_path()
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(value + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    return path


def clear_current_board() -> None:
    _current_path().unlink(missing_ok=True)


def board_exists(board: str | None = None) -> bool:
    value = _normalize_board_slug(board) or DEFAULT_BOARD
    return (_home() / "boards" / value).is_dir()


def read_board_metadata(board: str | None = None) -> dict[str, Any]:
    slug = _board_slug(board)
    path = _metadata_path(slug)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        value = {}
    return {
        "slug": slug,
        "name": str(
            value.get("name") or ("Default board" if slug == DEFAULT_BOARD else slug)
        ),
        "description": str(value.get("description") or ""),
        "icon": str(value.get("icon") or ""),
        "color": str(value.get("color") or ""),
        "archived": bool(value.get("archived", False)),
        "directory": _board_dir(slug),
        "db_path": _db_path(slug),
    }


def write_board_metadata(
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    icon: str | None = None,
    color: str | None = None,
    archived: bool | None = None,
) -> dict[str, Any]:
    value = _normalize_board_slug(slug)
    if not value or not board_exists(value):
        raise LookupError(f"board {slug!r} does not exist")
    current = read_board_metadata(value)
    for key, replacement in (
        ("name", name),
        ("description", description),
        ("icon", icon),
        ("color", color),
    ):
        if replacement is not None:
            current[key] = str(replacement)
    if archived is not None:
        current["archived"] = bool(archived)
    serializable = {
        key: current[key]
        for key in ("slug", "name", "description", "icon", "color", "archived")
    }
    _secure_directory(_board_dir(value))
    path = _metadata_path(value)
    path.write_text(
        json.dumps(serializable, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    path.chmod(0o600)
    return read_board_metadata(value)


def create_board(
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    icon: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    value = _normalize_board_slug(slug)
    if not value:
        raise ValueError("slug is required")
    if board_exists(value):
        return read_board_metadata(value)
    _secure_directory(_home() / "boards" / value)
    display_name = name or ("Default board" if value == DEFAULT_BOARD else value)
    write_board_metadata(
        value, name=display_name, description=description, icon=icon, color=color
    )
    init_db(board=value)
    return read_board_metadata(value)


def list_boards(*, include_archived: bool = True) -> list[dict[str, Any]]:
    if not board_exists(DEFAULT_BOARD):
        create_board(DEFAULT_BOARD)
    rows = []
    for path in sorted((_home() / "boards").iterdir(), key=lambda item: item.name):
        if not path.is_dir() or not _SLUG.fullmatch(path.name):
            continue
        meta = read_board_metadata(path.name)
        if include_archived or not meta["archived"]:
            rows.append(meta)
    return rows


def remove_board(slug: str, *, archive: bool = True) -> dict[str, Any]:
    value = _normalize_board_slug(slug)
    if not value or not board_exists(value):
        raise LookupError(f"board {slug!r} does not exist")
    if value == DEFAULT_BOARD and not archive:
        raise ValueError("the default board cannot be deleted")
    if archive:
        return write_board_metadata(value, archived=True)
    result = read_board_metadata(value)
    shutil.rmtree(_board_dir(value))
    if get_current_board() == value:
        clear_current_board()
    return result


def connect(*, board: str | None = None) -> sqlite3.Connection:
    path = _db_path(board)
    _secure_directory(path.parent)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def connect_closing(*, board: str | None = None):
    return closing(connect(board=board))


def init_db(*, board: str | None = None) -> None:
    with _SCHEMA_LOCK, connect_closing(board=board) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    path = _db_path(board)
    try:
        path.chmod(0o600)
    except OSError:
        pass


@contextmanager
def write_txn(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def _task(row: sqlite3.Row | None) -> Task | None:
    if row is None:
        return None
    try:
        skills = json.loads(row["skills"] or "[]")
    except ValueError:
        skills = []
    return Task(
        **{key: row[key] for key in Task.__dataclass_fields__ if key != "skills"},
        skills=skills,
    )


def _append_event(
    conn,
    task_id: str,
    kind: str,
    payload: dict | None = None,
    run_id: str | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO task_events(task_id,run_id,kind,payload,created_at) VALUES(?,?,?,?,?)",
        (
            task_id,
            run_id,
            kind,
            json.dumps(payload) if payload is not None else None,
            int(time.time()),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def create_task(
    conn,
    *,
    title: str,
    body: str | None = None,
    assignee: str | None = None,
    created_by: str | None = None,
    tenant: str | None = None,
    priority: int = 0,
    parents: Iterable[str] = (),
    triage: bool = False,
    workspace_kind: str = "scratch",
    workspace_path: str | None = None,
    idempotency_key: str | None = None,
    max_runtime_seconds: int | None = None,
    skills: list[str] | None = None,
) -> str:
    if idempotency_key:
        prior = conn.execute(
            "SELECT id FROM tasks WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if prior:
            return str(prior["id"])
    task_id = f"t_{uuid.uuid4().hex}"
    now = int(time.time())
    parent_ids = tuple(str(parent) for parent in parents)
    status = "triage" if triage else ("todo" if parent_ids else "ready")
    with write_txn(conn):
        conn.execute(
            "INSERT INTO tasks(id,title,body,status,assignee,created_by,tenant,priority,workspace_kind,workspace_path,idempotency_key,max_runtime_seconds,skills,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                title,
                body,
                status,
                assignee,
                created_by,
                tenant,
                int(priority),
                workspace_kind,
                workspace_path,
                idempotency_key,
                max_runtime_seconds,
                json.dumps(skills or []),
                now,
                now,
            ),
        )
        for parent in parent_ids:
            conn.execute(
                "INSERT OR IGNORE INTO task_links(parent_id,child_id) VALUES(?,?)",
                (parent, task_id),
            )
        conn.execute(
            "INSERT INTO task_events(task_id,kind,payload,created_at) VALUES(?,?,?,?)",
            (task_id, "created", json.dumps({"status": status}), now),
        )
    return task_id


def get_task(conn, task_id: str) -> Task | None:
    return _task(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())


def list_tasks(
    conn, *, tenant=None, assignee=None, include_archived=False, **_kwargs
) -> list[Task]:
    where, params = [], []
    if tenant:
        where.append("tenant=?")
        params.append(tenant)
    if assignee:
        where.append("assignee=?")
        params.append(assignee)
    if not include_archived:
        where.append("status!='archived'")
    sql = (
        "SELECT * FROM tasks"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY priority DESC, created_at"
    )
    return [
        task
        for row in conn.execute(sql, params).fetchall()
        if (task := _task(row)) is not None
    ]


def task_age(task: Task) -> int:
    return max(0, int(time.time()) - int(task.created_at))


def _transition(
    conn, task_id: str, status: str, kind: str, payload: dict | None = None, **fields
) -> bool:
    if not get_task(conn, task_id):
        return False
    now = int(time.time())
    assignments = ["status=?", "updated_at=?", *[f"{key}=?" for key in fields]]
    values = [status, now, *fields.values(), task_id]
    with write_txn(conn):
        conn.execute(f"UPDATE tasks SET {', '.join(assignments)} WHERE id=?", values)
        conn.execute(
            "INSERT INTO task_events(task_id,kind,payload,created_at) VALUES(?,?,?,?)",
            (task_id, kind, json.dumps(payload or {"status": status}), now),
        )
    return True


def assign_task(conn, task_id: str, assignee: str | None) -> bool:
    if not get_task(conn, task_id):
        return False
    conn.execute(
        "UPDATE tasks SET assignee=?,updated_at=? WHERE id=?",
        (assignee, int(time.time()), task_id),
    )
    conn.commit()
    _append_event(conn, task_id, "assigned", {"assignee": assignee})
    return True


def complete_task(conn, task_id: str, result=None, summary=None) -> bool:
    return _transition(
        conn,
        task_id,
        "done",
        "completed",
        {"result": result, "summary": summary},
        result=result,
        summary=summary,
    )


def block_task(conn, task_id: str, reason=None) -> bool:
    return _transition(
        conn, task_id, "blocked", "blocked", {"reason": reason}, block_reason=reason
    )


def unblock_task(conn, task_id: str) -> bool:
    return _transition(conn, task_id, "ready", "unblocked", block_reason=None)


def archive_task(conn, task_id: str) -> bool:
    return _transition(conn, task_id, "archived", "archived")


def set_task_status(conn, task_id: str, status: str) -> bool:
    """Apply a validated status without creating a parallel task mutation path."""
    normalized = str(status or "").strip().lower()
    if normalized not in {"triage", "todo", "ready", "running", "blocked", "done", "archived"}:
        raise ValueError(f"unsupported task status: {status!r}")
    return _transition(conn, task_id, normalized, "status_changed")


def add_comment(conn, task_id: str, author: str, body: str) -> int:
    now = int(time.time())
    cursor = conn.execute(
        "INSERT INTO task_comments(task_id,author,body,created_at) VALUES(?,?,?,?)",
        (task_id, author, body, now),
    )
    conn.commit()
    _append_event(conn, task_id, "commented", {"author": author})
    return int(cursor.lastrowid)


def list_comments(conn, task_id: str) -> list[Comment]:
    return [
        Comment(**dict(row))
        for row in conn.execute(
            "SELECT * FROM task_comments WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
    ]


def list_events(conn, task_id: str) -> list[Event]:
    rows = conn.execute(
        "SELECT * FROM task_events WHERE task_id=? ORDER BY id", (task_id,)
    ).fetchall()
    return [
        Event(
            id=row["id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            kind=row["kind"],
            payload=json.loads(row["payload"]) if row["payload"] else None,
            created_at=row["created_at"],
        )
        for row in rows
    ]


def list_runs(conn, task_id: str) -> list[Run]:
    return [
        Run(**dict(row))
        for row in conn.execute(
            "SELECT * FROM task_runs WHERE task_id=? ORDER BY started_at DESC",
            (task_id,),
        ).fetchall()
    ]


def link_tasks(conn, parent_id: str, child_id: str) -> bool:
    if parent_id == child_id:
        raise ValueError("a task cannot depend on itself")
    conn.execute(
        "INSERT OR IGNORE INTO task_links(parent_id,child_id) VALUES(?,?)",
        (parent_id, child_id),
    )
    conn.commit()
    _append_event(conn, child_id, "linked", {"parent_id": parent_id})
    return True


def unlink_tasks(conn, parent_id: str, child_id: str) -> bool:
    cursor = conn.execute(
        "DELETE FROM task_links WHERE parent_id=? AND child_id=?", (parent_id, child_id)
    )
    conn.commit()
    return cursor.rowcount == 1


def parent_ids(conn, task_id: str) -> list[str]:
    return [
        row["parent_id"]
        for row in conn.execute(
            "SELECT parent_id FROM task_links WHERE child_id=?", (task_id,)
        ).fetchall()
    ]


def child_ids(conn, task_id: str) -> list[str]:
    return [
        row["child_id"]
        for row in conn.execute(
            "SELECT child_id FROM task_links WHERE parent_id=?", (task_id,)
        ).fetchall()
    ]


def recompute_ready(conn) -> None:
    conn.execute(
        "UPDATE tasks SET status='ready',updated_at=? WHERE status='todo' AND NOT EXISTS (SELECT 1 FROM task_links l JOIN tasks p ON p.id=l.parent_id WHERE l.child_id=tasks.id AND p.status!='done')",
        (int(time.time()),),
    )
    conn.commit()


def known_assignees(conn) -> list[str]:
    return [
        row["assignee"]
        for row in conn.execute(
            "SELECT DISTINCT assignee FROM tasks WHERE assignee IS NOT NULL AND assignee!='' ORDER BY assignee"
        ).fetchall()
    ]


def board_stats(conn) -> dict[str, dict[str, int]]:
    by_status, by_assignee = {}, {}
    for row in conn.execute(
        "SELECT status,assignee,COUNT(*) n FROM tasks WHERE status!='archived' GROUP BY status,assignee"
    ).fetchall():
        count = int(row["n"])
        by_status[row["status"]] = by_status.get(row["status"], 0) + count
        owner = row["assignee"] or "unassigned"
        by_assignee[owner] = by_assignee.get(owner, 0) + count
    return {"by_status": by_status, "by_assignee": by_assignee}


def worker_log_path(task_id: str, *, board: str | None = None) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", task_id)
    return _board_dir(board) / "logs" / f"{safe_id}.log"


def read_worker_log(
    task_id: str, tail_bytes: int | None = None, *, board: str | None = None
) -> str | None:
    path = worker_log_path(task_id, board=board)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if tail_bytes:
        data = data[-int(tail_bytes) :]
    return data.decode("utf-8", errors="replace")


def _finish_delegated_task(
    board: str, task_id: str, run_id: str, delegation_id: str
) -> None:
    from api import delegation_tasks

    deadline = time.monotonic() + 24 * 60 * 60
    result = None
    while time.monotonic() < deadline:
        result = delegation_tasks.get_task(delegation_id)
        if result and delegation_tasks.is_terminal(str(result.get("status"))):
            break
        time.sleep(0.2)
    with connect_closing(board=board) as conn:
        now = int(time.time())
        if result and result.get("status") == delegation_tasks.STATUS_COMPLETED:
            complete_task(
                conn,
                task_id,
                result=result.get("result"),
                summary="delegated execution completed",
            )
        else:
            error = str((result or {}).get("error") or "delegated execution timed out")
            block_task(conn, task_id, reason=error)
        conn.execute(
            "UPDATE task_runs SET status=?,result=?,error=?,finished_at=? WHERE id=?",
            (
                (result or {}).get("status") or "failed",
                (result or {}).get("result"),
                (result or {}).get("error"),
                now,
                run_id,
            ),
        )
        conn.commit()


def _board_for_connection(conn: sqlite3.Connection) -> str:
    database = conn.execute("PRAGMA database_list").fetchone()
    if database:
        path = Path(str(database["file"])).resolve(strict=False)
        if path.name == "kanban.db" and path.parent.parent.name == "boards":
            candidate = _normalize_board_slug(path.parent.name)
            if candidate:
                return candidate
    return _board_slug(None)


def dispatch_once(conn, dry_run: bool = False, max_spawn: int = 8) -> dict[str, Any]:
    from api.backend_selector import get_active_backend
    from api.config import get_config

    rows = conn.execute(
        "SELECT * FROM tasks WHERE status='ready' ORDER BY priority DESC,created_at LIMIT ?",
        (max(1, int(max_spawn)),),
    ).fetchall()
    candidates = [task for row in rows if (task := _task(row)) is not None]
    if dry_run:
        return {
            "dry_run": True,
            "max_spawn": max_spawn,
            "candidates": [task.id for task in candidates],
            "spawned": [],
        }
    board = _board_for_connection(conn)
    spawned = []
    for task in candidates:
        from api.delegation_runner import delegate

        backend = task.assignee or get_active_backend(get_config())
        prompt = f"{task.title}\n\n{task.body or ''}".strip()
        delegated = delegate(prompt=prompt, backend=backend)
        run_id = uuid.uuid4().hex
        now = int(time.time())
        with write_txn(conn):
            conn.execute(
                "INSERT INTO task_runs(id,task_id,delegation_id,status,started_at) VALUES(?,?,?,?,?)",
                (run_id, task.id, delegated["id"], "running", now),
            )
            conn.execute(
                "UPDATE tasks SET status='running',current_run_id=?,updated_at=? WHERE id=?",
                (run_id, now, task.id),
            )
            conn.execute(
                "INSERT INTO task_events(task_id,run_id,kind,payload,created_at) VALUES(?,?,?,?,?)",
                (
                    task.id,
                    run_id,
                    "dispatched",
                    json.dumps({"backend": backend, "delegation_id": delegated["id"]}),
                    now,
                ),
            )
        threading.Thread(
            target=_finish_delegated_task,
            args=(board, task.id, run_id, delegated["id"]),
            daemon=True,
            name=f"kanban-{task.id[2:10]}",
        ).start()
        spawned.append(
            {"task_id": task.id, "delegation_id": delegated["id"], "backend": backend}
        )
    return {"dry_run": False, "max_spawn": max_spawn, "spawned": spawned}


def _end_run(
    conn, task_id: str, *, outcome: str, status: str, summary: str | None = None
):
    task = get_task(conn, task_id)
    if not task:
        return None
    row = conn.execute(
        "SELECT current_run_id FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    run_id = row["current_run_id"] if row else None
    if run_id:
        conn.execute(
            "UPDATE task_runs SET status=?,result=?,finished_at=? WHERE id=?",
            (status, summary, int(time.time()), run_id),
        )
        conn.commit()
    return run_id
