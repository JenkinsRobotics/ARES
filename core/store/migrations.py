"""Ordered, versioned, recoverable schema migration for authoritative SQLite.

Phase 0 finding F4: ARES holds eleven SQLite databases — including a 1.06 GB
``context_store.db`` and a 296 MB ``journal.db`` of real personal state — and
had no schema-versioning system at all. ``PRAGMA user_version`` was 0
everywhere; schema evolution was 27 ``CREATE TABLE IF NOT EXISTS`` calls at
open time plus three ``ALTER TABLE``s wrapped in per-column ``try/except`` that
recorded ``"error: ..."`` into a dict the HTTP route returned with a 200.

That arrangement cannot answer the two questions this data layer has to answer
for years: *what shape is this database in* and *did the last upgrade actually
work*. This module answers both.

Design notes, and why each choice rather than the obvious alternative:

**``PRAGMA user_version``, not a version table.** It is a four-byte field in
the database header, written inside the same transaction as the DDL it
describes, so version and shape can never disagree — there is no window where
the tables moved but the row recording it did not. It also costs nothing on the
existing databases: they already read 0, which is exactly "before migration 1".
A ``schema_version`` table (jaeger-agent's ``state.db`` uses one) needs its own
CREATE before it can be read, which is a migration problem of its own.

**Refuse to open a database from the future.** A newer ARES may have moved the
schema past what this build understands. Running anyway would corrupt it
quietly. Refusing is recoverable; the operator downgrades or upgrades.

**One transaction per migration, not one for all of them.** SQLite DDL is
transactional, so a failing migration rolls back to the version boundary before
it. That is what makes ``PARTIAL_FAILURE`` an honest, recoverable state rather
than an unknown one: everything below the reported version is applied and
committed, the failing one is fully undone, and re-running resumes there.

**Backup before the first destructive step, using the online backup API.**
``Connection.backup()` is WAL-safe and consistent under a live reader; copying
the file with ``shutil`` is neither.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "Migration",
    "MigrationError",
    "MigrationReport",
    "MigrationStatus",
    "backup_database",
    "current_version",
    "migrate",
]


class MigrationStatus(str, Enum):
    """Outcome of a migration run. ``str`` so it serialises as itself.

    The three values are deliberately not collapsible into a boolean: a caller
    that only distinguishes ok/not-ok cannot tell a database that never moved
    from one that moved halfway, and those need different operator responses.
    """

    SUCCESS = "success"                  # at target version; nothing failed
    PARTIAL_FAILURE = "partial_failure"  # some applied and committed, then one failed
    FAILED = "failed"                    # nothing applied; still at the starting version


class MigrationError(RuntimeError):
    """A migration could not be applied. Carries where it stopped."""

    def __init__(self, message: str, *, version: int, applied: Sequence[int] = ()) -> None:
        super().__init__(message)
        self.version = version
        self.applied = list(applied)


@dataclass(frozen=True)
class Migration:
    """One forward step.

    ``apply`` receives an open connection inside an already-started
    transaction. It must not commit, roll back, or close — the runner owns the
    transaction boundary, which is the only way the version stamp and the DDL
    can land atomically.
    """

    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]
    destructive: bool = False   # drops/rewrites data → back up before running

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("migration versions start at 1; 0 means 'unmigrated'")


@dataclass
class MigrationReport:
    """What happened, in a shape a route or a log line can render directly."""

    status: MigrationStatus
    database: str
    version_before: int
    version_after: int
    applied: list[str] = field(default_factory=list)
    failed: str | None = None
    error: str | None = None
    backup_path: str | None = None
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status is MigrationStatus.SUCCESS

    def as_dict(self) -> dict:
        return {
            "status": self.status.value,
            "database": self.database,
            "version_before": self.version_before,
            "version_after": self.version_after,
            "applied": list(self.applied),
            "failed": self.failed,
            "error": self.error,
            "backup_path": self.backup_path,
            "duration_s": round(self.duration_s, 3),
        }


def current_version(conn: sqlite3.Connection) -> int:
    """The schema version recorded in the database header (0 = unmigrated)."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    # PRAGMA cannot take a bound parameter, so the value is interpolated —
    # safe only because it is an int we validated on the way in. Keep the
    # int() call: it is the sanitiser, not a formality.
    conn.execute(f"PRAGMA user_version = {int(version)}")


def backup_database(path: Path, *, suffix: str | None = None) -> Path:
    """Consistent copy of ``path`` beside it, via SQLite's online backup.

    Used before destructive migrations. ``Connection.backup()`` rather than a
    file copy because these databases run in WAL mode: copying the main file
    alone loses whatever is still in the -wal, producing a backup that is
    silently behind the original — the worst possible kind.
    """
    stamp = suffix or time.strftime("%Y%m%dT%H%M%S")
    target = path.with_name(f"{path.name}.pre-migration-{stamp}.bak")
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    logger.info("migration backup written: %s", target)
    return target


def migrate(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration],
    *,
    database_path: Path | None = None,
    allow_backup: bool = True,
) -> MigrationReport:
    """Bring ``conn`` up to the highest version in ``migrations``.

    Idempotent: a database already at the target applies nothing and reports
    SUCCESS, which is what makes this safe to call unconditionally at startup.

    Raises :class:`MigrationError` only for a database NEWER than this build
    understands — a state no amount of retrying fixes, and one where continuing
    would write an old shape over a new one. Every other failure is returned as
    a report, because the caller needs to log it, surface it, and decide.
    """
    ordered = sorted(migrations, key=lambda m: m.version)
    versions = [m.version for m in ordered]
    if len(set(versions)) != len(versions):
        raise ValueError(f"duplicate migration versions: {versions}")

    started = time.monotonic()
    name = str(database_path) if database_path is not None else "<connection>"
    before = current_version(conn)
    target = versions[-1] if versions else 0

    if before > target:
        raise MigrationError(
            f"{name} is at schema v{before} but this build knows only v{target}. "
            "It was written by a newer ARES; upgrade rather than downgrade.",
            version=before,
        )

    pending = [m for m in ordered if m.version > before]
    if not pending:
        return MigrationReport(
            status=MigrationStatus.SUCCESS, database=name,
            version_before=before, version_after=before,
            duration_s=time.monotonic() - started,
        )

    backup_path: Path | None = None
    if allow_backup and database_path is not None and any(m.destructive for m in pending):
        try:
            backup_path = backup_database(database_path)
        except Exception as exc:  # noqa: BLE001 — reported, never swallowed
            # Refusing to proceed is the point: a destructive migration with no
            # recovery copy is exactly the operation this module exists to
            # prevent from happening silently.
            return MigrationReport(
                status=MigrationStatus.FAILED, database=name,
                version_before=before, version_after=before,
                error=f"refused: could not back up before a destructive migration: {exc}",
                duration_s=time.monotonic() - started,
            )

    applied: list[str] = []
    version = before
    for migration in pending:
        label = f"v{migration.version}:{migration.name}"
        try:
            # BEGIN IMMEDIATE takes the write lock up front rather than on the
            # first write, so a concurrent writer fails here — before any DDL —
            # instead of halfway through with a busy error.
            conn.execute("BEGIN IMMEDIATE")
            migration.apply(conn)
            _set_version(conn, migration.version)
            conn.execute("COMMIT")
        except Exception as exc:  # noqa: BLE001 — the report IS the handling
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            landed = current_version(conn)
            status = (MigrationStatus.PARTIAL_FAILURE if applied
                      else MigrationStatus.FAILED)
            logger.error("migration %s failed on %s: %s", label, name, exc)
            return MigrationReport(
                status=status, database=name,
                version_before=before, version_after=landed,
                applied=applied, failed=label, error=str(exc),
                backup_path=str(backup_path) if backup_path else None,
                duration_s=time.monotonic() - started,
            )
        applied.append(label)
        version = migration.version
        logger.info("migration applied: %s on %s", label, name)

    return MigrationReport(
        status=MigrationStatus.SUCCESS, database=name,
        version_before=before, version_after=version, applied=applied,
        backup_path=str(backup_path) if backup_path else None,
        duration_s=time.monotonic() - started,
    )


def discard_backup(path: Path | str | None) -> None:
    """Remove a backup once the caller has confirmed the upgrade is good.

    Separate from :func:`migrate` on purpose: the runner must never be the
    thing that decides a copy of irreplaceable state is no longer needed.
    """
    if not path:
        return
    with_suffix = Path(path)
    if ".pre-migration-" not in with_suffix.name:
        raise ValueError(f"refusing to delete {with_suffix}: not a migration backup")
    shutil.rmtree(with_suffix, ignore_errors=True) if with_suffix.is_dir() else with_suffix.unlink(missing_ok=True)
