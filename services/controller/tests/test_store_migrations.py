"""The migration runner must never let a failed upgrade look like a good one.

Phase 0 finding F4. These tests care much less about the happy path than about
what the database looks like AFTER something goes wrong — that is the property
the old ``try/except`` per column could not offer, and the reason a 1.06 GB
``context_store.db`` and a 296 MB ``journal.db`` of real personal state needed
this before anything else touched them.

The fixtures build genuinely old-shaped databases rather than mocking a
version number, because the thing being tested is whether real rows survive a
real transformation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.store.migrations import (
    Migration,
    MigrationError,
    MigrationStatus,
    backup_database,
    current_version,
    migrate,
)


# ── fixtures shaped like the databases actually on disk ────────────────


def _legacy_journal(path: Path) -> sqlite3.Connection:
    """A pre-versioning journal: real columns, real rows, user_version 0.

    Mirrors what ``~/.ares/journal/journal.db`` looks like today — created by
    ``CREATE TABLE IF NOT EXISTS`` at open time, never stamped with a version.
    """
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT, created_at REAL);
        CREATE TABLE documents (id TEXT PRIMARY KEY, body TEXT, created_at REAL);
        """
    )
    conn.executemany(
        "INSERT INTO conversations VALUES (?, ?, ?)",
        [("c1", "first", 1.0), ("c2", "second", 2.0)],
    )
    conn.executemany(
        "INSERT INTO documents VALUES (?, ?, ?)",
        [("d1", "hello", 1.0), ("d2", "world", 2.0)],
    )
    conn.commit()
    return conn


def _add_sensitivity(conn: sqlite3.Connection) -> None:
    """The real v1 step: the SI sensitivity columns, done atomically."""
    conn.execute("ALTER TABLE conversations ADD COLUMN sensitivity TEXT DEFAULT 'personal'")
    conn.execute("ALTER TABLE conversations ADD COLUMN importance REAL DEFAULT 0.5")


def _add_plans(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE plans (plan_id TEXT PRIMARY KEY, goal TEXT)")


def _explode(_conn: sqlite3.Connection) -> None:
    raise sqlite3.OperationalError("no such column: nope")


@pytest.fixture
def legacy_db(tmp_path):
    path = tmp_path / "journal.db"
    conn = _legacy_journal(path)
    yield path, conn
    conn.close()


# ── the ordinary path ──────────────────────────────────────────────────


def test_a_legacy_database_migrates_forward_with_its_data_intact(legacy_db):
    path, conn = legacy_db
    assert current_version(conn) == 0, "fixture must start unversioned, like production"

    report = migrate(
        conn,
        [Migration(1, "sensitivity", _add_sensitivity),
         Migration(2, "plans", _add_plans)],
        database_path=path,
    )

    assert report.status is MigrationStatus.SUCCESS
    assert report.ok
    assert (report.version_before, report.version_after) == (0, 2)
    assert report.applied == ["v1:sensitivity", "v2:plans"]
    assert current_version(conn) == 2
    # The rows that existed before are still there, with the new default filled.
    rows = conn.execute(
        "SELECT id, title, sensitivity, importance FROM conversations ORDER BY id"
    ).fetchall()
    assert rows == [("c1", "first", "personal", 0.5), ("c2", "second", "personal", 0.5)]
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2


def test_running_again_changes_nothing(legacy_db):
    """Idempotence is what licenses calling this on every startup."""
    path, conn = legacy_db
    steps = [Migration(1, "sensitivity", _add_sensitivity)]
    migrate(conn, steps, database_path=path)

    report = migrate(conn, steps, database_path=path)

    assert report.status is MigrationStatus.SUCCESS
    assert report.applied == [], "a second run re-applied a migration"
    assert (report.version_before, report.version_after) == (1, 1)


# ── the paths that used to lie ─────────────────────────────────────────


def test_a_failure_on_the_first_step_leaves_the_database_untouched(legacy_db):
    path, conn = legacy_db

    report = migrate(conn, [Migration(1, "boom", _explode)], database_path=path)

    assert report.status is MigrationStatus.FAILED
    assert not report.ok
    assert report.failed == "v1:boom"
    assert "no such column" in (report.error or "")
    assert current_version(conn) == 0, "a failed migration moved the version"
    # And the schema is genuinely unchanged, not merely unstamped.
    columns = {r[1] for r in conn.execute("PRAGMA table_info(conversations)")}
    assert "sensitivity" not in columns


def test_a_later_failure_reports_partial_and_stops_at_the_last_good_version(legacy_db):
    """The distinction that a boolean cannot carry.

    Two migrations committed, the third rolled back. The database is coherent
    at v2 — not corrupt, not at target — and re-running must resume at v3
    rather than replay v1 and v2.
    """
    path, conn = legacy_db

    report = migrate(
        conn,
        [Migration(1, "sensitivity", _add_sensitivity),
         Migration(2, "plans", _add_plans),
         Migration(3, "boom", _explode)],
        database_path=path,
    )

    assert report.status is MigrationStatus.PARTIAL_FAILURE
    assert not report.ok
    assert report.applied == ["v1:sensitivity", "v2:plans"]
    assert report.failed == "v3:boom"
    assert report.version_after == 2
    assert current_version(conn) == 2
    # v1 and v2 really landed; v3 really did not.
    assert conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0


def test_the_failing_step_is_rolled_back_not_half_applied(legacy_db):
    """DDL before the failure inside ONE migration must not survive it."""
    path, conn = legacy_db

    def _half(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE partial_a (x TEXT)")
        raise sqlite3.OperationalError("failed after the first statement")

    report = migrate(conn, [Migration(1, "half", _half)], database_path=path)

    assert report.status is MigrationStatus.FAILED
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "partial_a" not in tables, "a rolled-back migration left a table behind"


def test_a_database_from_the_future_is_refused_loudly(legacy_db):
    """Writing an old shape over a newer one is unrecoverable; refusing is not."""
    path, conn = legacy_db
    conn.execute("PRAGMA user_version = 9")

    with pytest.raises(MigrationError) as caught:
        migrate(conn, [Migration(1, "sensitivity", _add_sensitivity)], database_path=path)

    assert caught.value.version == 9
    assert "newer ARES" in str(caught.value)
    assert current_version(conn) == 9


def test_duplicate_versions_are_a_programming_error(legacy_db):
    path, conn = legacy_db
    with pytest.raises(ValueError, match="duplicate migration versions"):
        migrate(
            conn,
            [Migration(1, "a", _add_plans), Migration(1, "b", _add_plans)],
            database_path=path,
        )


def test_version_zero_is_rejected_as_a_migration():
    """0 means 'unmigrated'; a step numbered 0 could never be pending."""
    with pytest.raises(ValueError, match="versions start at 1"):
        Migration(0, "impossible", _add_plans)


# ── backup and recovery ────────────────────────────────────────────────


def test_a_destructive_migration_backs_up_first_and_the_copy_is_usable(legacy_db):
    path, conn = legacy_db

    def _drop_documents(c: sqlite3.Connection) -> None:
        c.execute("DROP TABLE documents")

    report = migrate(
        conn,
        [Migration(1, "drop-documents", _drop_documents, destructive=True)],
        database_path=path,
    )

    assert report.status is MigrationStatus.SUCCESS
    assert report.backup_path, "a destructive migration ran with no recovery copy"
    backup = Path(report.backup_path)
    assert backup.exists()
    # The whole point: the dropped data is recoverable from the backup.
    restored = sqlite3.connect(backup)
    try:
        assert restored.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
    finally:
        restored.close()


def test_a_non_destructive_migration_does_not_copy_a_gigabyte(legacy_db):
    """Backups are for destructive steps only — context_store.db is 1.06 GB."""
    path, conn = legacy_db
    report = migrate(
        conn, [Migration(1, "sensitivity", _add_sensitivity)], database_path=path)
    assert report.backup_path is None
    assert not list(path.parent.glob("*.bak"))


def test_a_failed_backup_refuses_to_run_the_migration(legacy_db, monkeypatch):
    """No recovery copy means the destructive step must not happen at all."""
    path, conn = legacy_db

    def _no_disk(*_a, **_k):
        raise OSError("No space left on device")

    monkeypatch.setattr("core.store.migrations.backup_database", _no_disk)

    def _drop_documents(c: sqlite3.Connection) -> None:
        c.execute("DROP TABLE documents")

    report = migrate(
        conn,
        [Migration(1, "drop-documents", _drop_documents, destructive=True)],
        database_path=path,
    )

    assert report.status is MigrationStatus.FAILED
    assert "could not back up" in (report.error or "")
    assert current_version(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2


def test_backup_of_a_wal_database_is_consistent(tmp_path):
    """The stores in production run WAL; a file copy would lose the -wal."""
    path = tmp_path / "wal.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(500)])
    conn.commit()          # committed into the -wal, not yet checkpointed
    try:
        backup = backup_database(path)
        restored = sqlite3.connect(backup)
        try:
            assert restored.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 500
        finally:
            restored.close()
    finally:
        conn.close()


# ── the report is what a route/log/UI renders ──────────────────────────


def test_the_report_serialises_without_losing_the_failure(legacy_db):
    path, conn = legacy_db
    report = migrate(
        conn,
        [Migration(1, "sensitivity", _add_sensitivity), Migration(2, "boom", _explode)],
        database_path=path,
    )
    payload = report.as_dict()

    assert payload["status"] == "partial_failure"
    assert payload["failed"] == "v2:boom"
    assert payload["error"]
    assert payload["version_after"] == 1
    # A caller that only checks a truthy status must not read this as fine.
    assert payload["status"] != "success"
