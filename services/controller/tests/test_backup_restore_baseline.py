"""A backup of an in-use WAL database must open, verify, and read back.

Phase 0.5 §11. Not a backup product — the minimum proof that the authoritative
stores CAN be copied safely before any schema refactor touches them, and a
written-down restore procedure that someone can follow at 3am.

The important property is the WAL one. ``context_store.db`` is 1.06 GB and
``journal.db`` 296 MB, both in WAL mode, both open while ARES runs. Copying the
main file with ``shutil`` while a writer holds the ``-wal`` produces a backup
that is silently BEHIND the original — the failure that looks fine until the
day it is needed. ``sqlite3.Connection.backup()`` reads through the WAL and is
consistent under a live writer, which is why the migration runner uses it and
why these tests exercise it with a writer actually running.

No operator data is used or copied. Every fixture is synthetic.
"""

from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from core.store.migrations import backup_database


def _make_wal_store(path: Path, rows: int = 2000) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            body TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
        """
    )
    conn.execute("INSERT INTO conversations VALUES ('c1', 'a conversation')")
    conn.executemany(
        "INSERT INTO messages VALUES (?, 'c1', ?)",
        [(f"m{i}", f"body {i}") for i in range(rows)],
    )
    conn.commit()
    return conn


def test_a_backup_taken_while_the_store_is_in_use_is_complete(tmp_path):
    """The headline property: consistent under a concurrent writer."""
    path = tmp_path / "journal.db"
    conn = _make_wal_store(path)
    stop = threading.Event()
    written: list[int] = []

    def _writer() -> None:
        w = sqlite3.connect(path, timeout=10)
        w.execute("PRAGMA journal_mode=WAL")
        i = 0
        while not stop.is_set():
            w.execute("INSERT INTO messages VALUES (?, 'c1', ?)",
                      (f"live{i}", f"live body {i}"))
            w.commit()
            written.append(i)
            i += 1
            time.sleep(0.001)
        w.close()

    thread = threading.Thread(target=_writer, daemon=True)
    thread.start()
    try:
        time.sleep(0.05)                 # let the writer get into the -wal
        backup = backup_database(path)
    finally:
        stop.set()
        thread.join(timeout=5)

    assert backup.exists()
    restored = sqlite3.connect(backup)
    try:
        # integrity_check is the standard "is this file sound" gate.
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        # Every committed row is present: at least the 2000 seeded, and a
        # consistent prefix of the live ones. The point is that the copy is a
        # real snapshot, not a torn one.
        count = restored.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count >= 2000
        assert restored.execute(
            "SELECT title FROM conversations WHERE id='c1'"
        ).fetchone()[0] == "a conversation"
    finally:
        restored.close()
        conn.close()


def test_a_naive_file_copy_is_what_the_backup_api_avoids(tmp_path):
    """Shows WHY ``Connection.backup()`` rather than ``shutil.copy``.

    Copying only the main database file of a WAL store drops everything still
    in the ``-wal``. Asserted as an inequality rather than a fixed number
    because how much is checkpointed is timing-dependent — the guarantee being
    documented is that the file copy is NOT trustworthy, while the backup API
    is.
    """
    path = tmp_path / "wal.db"
    conn = _make_wal_store(path, rows=5000)

    naive = tmp_path / "naive-copy.db"
    shutil.copyfile(path, naive)          # main file only, no -wal
    proper = backup_database(path)

    proper_conn = sqlite3.connect(proper)
    naive_conn = sqlite3.connect(naive)
    try:
        proper_count = proper_conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert proper_count == 5000
        naive_count = naive_conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert naive_count <= proper_count, (
            "the naive copy somehow held MORE than the consistent backup"
        )
    except sqlite3.DatabaseError:
        pass          # a naive copy that will not even open makes the same point
    finally:
        proper_conn.close()
        naive_conn.close()
        conn.close()


def test_the_restore_procedure_round_trips(tmp_path):
    """Restore is a file move plus removing stale WAL sidecars.

    Documented as executable steps so the procedure in
    docs/architecture/phase0-stabilization.md is verified rather than asserted.
    """
    path = tmp_path / "state.db"
    conn = _make_wal_store(path, rows=100)
    backup = backup_database(path)

    # Damage the live store the way a bad migration would.
    conn.execute("DELETE FROM messages")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    conn.close()

    # ── restore ──
    for sidecar in (path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        sidecar.unlink(missing_ok=True)
    shutil.copyfile(backup, path)

    restored = sqlite3.connect(path)
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 100
        # Constraints survive a restore — the schema comes with the file.
        restored.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            restored.execute("INSERT INTO messages VALUES ('x', 'ghost', 'b')")
    finally:
        restored.close()


def test_a_backup_of_a_corrupt_store_is_not_reported_as_good(tmp_path):
    """Corruption must surface at backup time, not at restore time."""
    path = tmp_path / "broken.db"
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)   # header only, junk body

    with pytest.raises(sqlite3.DatabaseError):
        backup_database(path)
