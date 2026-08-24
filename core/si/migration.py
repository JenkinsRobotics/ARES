"""
ARES SI — Journal schema migrations.

Adds the sensitivity/importance/tags/is_decision columns the Trust Engine and
Context Compiler filter on, plus the plan/step tables the orchestrator writes.

Phase 0 (finding F4) rebuilt this on :mod:`core.store.migrations`. What it used
to be: three loops of ``ALTER TABLE`` in per-column ``try/except``, each writing
either ``"added"``, ``"already_exists"`` or the string ``f"error: {e}"`` into a
results dict — which ``POST /si/migrate`` then returned with HTTP 200. A caller
could not distinguish a clean migration from a completely failed one without
string-matching the values, and nothing logged, alerted, or retried. On a
296 MB journal of real personal state that is not an acceptable way to find out
an upgrade did not happen.

What changed, and what deliberately did not:

* **Versioned.** ``PRAGMA user_version`` now records how far the journal has
  come, so the answer to "is this database migrated?" is a number rather than
  an inference from which columns happen to exist.
* **Atomic per step.** Each migration runs in its own transaction. A failure
  rolls that step back whole; earlier steps stay committed and the version
  stamp matches the shape exactly.
* **Missing optional tables are SKIPPED, not failed.** ``documents`` and
  ``messages`` are created lazily by the journal's own open path, so a young
  journal legitimately lacks them. Skipping is recorded in the report — the
  distinction between "nothing to do" and "could not do it" is the whole point
  and must not collapse back into one bucket.
* **The legacy dict return is preserved.** ``migrate_journal_sensitivity``
  still answers in the old ``{key: status}`` shape for existing callers; it is
  now derived from a real report rather than assembled from swallowed
  exceptions. New code should call :func:`migrate_journal` and read the report.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from core.store.migrations import (
    Migration,
    MigrationReport,
    MigrationStatus,
    migrate,
)

logger = logging.getLogger(__name__)

__all__ = [
    "JOURNAL_MIGRATIONS",
    "JOURNAL_SCHEMA_VERSION",
    "migrate_journal",
    "migrate_journal_sensitivity",
]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


_SENSITIVITY_COLUMNS = (
    ("sensitivity", "TEXT", "'personal'"),
    ("importance", "REAL", "0.5"),
    ("tags", "TEXT", "'[]'"),
    ("is_decision", "INTEGER", "0"),
)

# Tables that the journal creates lazily. Absent is normal on a young journal
# and must not be reported as an error — see the module docstring.
_OPTIONAL_TABLES = ("conversations", "documents", "messages")

_SKIPPED: list[str] = []


def _add_sensitivity_columns(conn: sqlite3.Connection) -> None:
    """v1 — the SI filtering columns, added only where the table exists.

    ``ADD COLUMN`` is checked against ``PRAGMA table_info`` rather than caught
    as a "duplicate column" error, so a genuine failure (a locked database, a
    disk error) still propagates and rolls the step back instead of being
    mistaken for "already applied".
    """
    for table in _OPTIONAL_TABLES:
        if not _table_exists(conn, table):
            _SKIPPED.append(f"{table}: table absent")
            continue
        existing = _columns(conn, table)
        for column, sql_type, default in _SENSITIVITY_COLUMNS:
            if column in existing:
                continue
            conn.execute(
                f'ALTER TABLE "{table}" ADD COLUMN {column} {sql_type} DEFAULT {default}'
            )


def _create_plan_tables(conn: sqlite3.Connection) -> None:
    """v2 — the orchestrator's plan/step state."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plans (
            plan_id TEXT PRIMARY KEY,
            goal TEXT,
            status TEXT DEFAULT 'pending',
            conversation_id TEXT,
            created_at REAL,
            updated_at REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS steps (
            step_id TEXT PRIMARY KEY,
            plan_id TEXT,
            objective TEXT,
            dependencies TEXT DEFAULT '[]',
            required_capabilities TEXT DEFAULT '[]',
            assigned_worker TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            evaluation TEXT,
            retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 2,
            requires_approval INTEGER DEFAULT 0,
            FOREIGN KEY (plan_id) REFERENCES plans(plan_id)
        )
        """
    )


JOURNAL_MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "si-sensitivity-columns", _add_sensitivity_columns),
    Migration(2, "si-plan-tables", _create_plan_tables),
)

JOURNAL_SCHEMA_VERSION = max(m.version for m in JOURNAL_MIGRATIONS)


def migrate_journal(
    conn: sqlite3.Connection, *, database_path: Path | None = None
) -> MigrationReport:
    """Bring a journal database up to :data:`JOURNAL_SCHEMA_VERSION`.

    Idempotent — safe to call on every startup, which is the point: the old
    migration ran only when an operator remembered to POST to an endpoint, so
    whether the columns existed depended on whether somebody had done that.
    """
    _SKIPPED.clear()
    report = migrate(conn, JOURNAL_MIGRATIONS, database_path=database_path)
    if _SKIPPED:
        logger.info("journal migration skipped absent tables: %s", ", ".join(_SKIPPED))
    if not report.ok:
        logger.error(
            "journal migration did not complete: status=%s failed=%s error=%s",
            report.status.value, report.failed, report.error,
        )
    return report


def migrate_journal_sensitivity(db: sqlite3.Connection) -> dict:
    """Legacy entry point — same ``{key: status}`` shape as before.

    Kept so existing callers keep working, but the values now come from a real
    migration report instead of per-column exception text. A caller that wants
    to know whether the migration SUCCEEDED should use :func:`migrate_journal`
    and read ``report.status``; this dict cannot express partial failure
    unambiguously, which is exactly why it stopped being the primary interface.
    """
    report = migrate_journal(db)
    results: dict[str, str] = {}

    applied_v1 = any(item.startswith("v1:") for item in report.applied)
    for table in _OPTIONAL_TABLES:
        absent = any(item.startswith(f"{table}:") for item in _SKIPPED)
        for column, _type, _default in _SENSITIVITY_COLUMNS:
            key = f"{table}.{column}"
            if absent:
                results[key] = "skipped: table absent"
            elif applied_v1:
                results[key] = "added"
            else:
                results[key] = "already_exists"

    plan_state = "created" if any(item.startswith("v2:") for item in report.applied) else "already_exists"
    results["plans_table"] = plan_state
    results["steps_table"] = plan_state

    if not report.ok:
        # Surface the failure in a value no caller can read as success, and
        # keep the structured status alongside it.
        results["status"] = report.status.value
        results["error"] = report.error or "migration failed"
    else:
        results["status"] = MigrationStatus.SUCCESS.value
    return results
