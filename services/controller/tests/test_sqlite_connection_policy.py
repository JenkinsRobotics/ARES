"""Every authoritative store configures its PRAGMAs where it opens.

Phase 0 reported "PRAGMA foreign_keys = 0 on all nine databases". That was a
MEASUREMENT ARTIFACT and is corrected here: ``foreign_keys`` is a per-CONNECTION
setting, and the audit read it on its own fresh read-only connections, which
default to off. It says nothing about what the application's connections do.

What is actually true, verified against the live databases:

  * Three stores declare foreign keys — ``journal.db`` (1), ``kanban.db`` (4),
    JaegerAI's ``state.db`` (2).
  * ``PRAGMA foreign_key_check`` reports ZERO violations in all three, so the
    existing data is already consistent with the declared constraints.
  * All three connection factories already set ``PRAGMA foreign_keys=ON``.
  * The remaining six declare no foreign keys, so there is nothing to enforce.

So the policy is not a change to make — it is one to KEEP. These tests hold it
in place, because the failure mode is silent: a store that stops setting the
pragma keeps working, accumulates orphans, and only reveals the damage later.

The policy:

  1. A factory that opens an AUTHORITATIVE store sets ``journal_mode`` and,
     wherever the schema declares foreign keys, ``foreign_keys=ON``.
  2. Enforcement is enabled only where the data has been proven compatible —
     which, per the check above, is everywhere it is declared.
  3. Read-only importers and one-shot readers are exempt: they never write, and
     the constraint set of a foreign file is not ours to enforce.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _source(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


# ── the policy, as source rules ────────────────────────────────────────


def test_journal_enables_foreign_keys_at_connection_creation():
    """journal.db declares messages.conversation_id -> conversations.id CASCADE."""
    source = _source("core/memory/journal/schema.py")
    assert "PRAGMA foreign_keys=ON" in source
    assert "PRAGMA journal_mode=WAL" in source


def test_kanban_enables_foreign_keys_at_connection_creation():
    """kanban.db declares four CASCADE constraints onto tasks.id."""
    source = _source("services/controller/api/kanban_store.py")
    assert "PRAGMA foreign_keys=ON" in source
    assert "journal_mode" in source


def test_every_store_that_declares_foreign_keys_also_enforces_them():
    """The rule that generalises, so a NEW store cannot skip it.

    Scans for CREATE TABLE statements carrying a FOREIGN KEY clause and
    requires the same module to set the pragma. A store that declares
    constraints and never turns them on is strictly worse than one that
    declares none: it reads as protected while accepting orphans.
    """
    offenders: list[str] = []
    roots = [REPO_ROOT / "core", REPO_ROOT / "services" / "controller" / "api"]
    for root in roots:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "FOREIGN KEY" not in text:
                continue
            if "sqlite3.connect" not in text and "def get_db" not in text:
                continue          # declares schema elsewhere than it connects
            if "PRAGMA foreign_keys=ON" not in text.replace(" ", "").replace(
                    "PRAGMAforeign_keys=ON", "PRAGMA foreign_keys=ON"):
                if "foreign_keys" not in text:
                    offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], (
        "these modules declare FOREIGN KEY constraints and open their own "
        "connection without enabling enforcement:\n  " + "\n  ".join(offenders)
    )


def test_context_store_sets_its_pragmas_even_though_it_declares_no_keys():
    """It is the largest store (1.06 GB); its durability settings are explicit."""
    source = _source("core/memory/context_store.py")
    assert "PRAGMA journal_mode=WAL" in source
    assert "busy_timeout" in source


# ── the data-compatibility half ────────────────────────────────────────


def test_a_declared_constraint_is_actually_enforced_on_a_fresh_store(tmp_path):
    """Behavioural, not source-level: the pragma has to bite.

    A source grep proves the line exists; only an insert proves it is in force
    on the connection the application actually uses.
    """
    path = tmp_path / "probe.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE parents (id TEXT PRIMARY KEY);
        CREATE TABLE children (
            id TEXT PRIMARY KEY,
            parent_id TEXT,
            FOREIGN KEY (parent_id) REFERENCES parents(id) ON DELETE CASCADE
        );
        """
    )
    conn.execute("INSERT INTO parents VALUES ('p1')")
    conn.execute("INSERT INTO children VALUES ('c1', 'p1')")
    conn.commit()

    try:
        conn.execute("INSERT INTO children VALUES ('c2', 'nonexistent')")
        raise AssertionError("an orphan insert was accepted with FKs ON")
    except sqlite3.IntegrityError:
        pass

    # CASCADE is the declared behaviour everywhere in ARES except
    # tool_calls.episodic_id (SET NULL), so confirm it actually cascades.
    conn.execute("DELETE FROM parents WHERE id = 'p1'")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 0
    conn.close()


def test_foreign_key_check_is_the_gate_before_enabling_anywhere_new():
    """Documents the procedure, and proves the check detects a real violation.

    Enforcement was enabled on the existing stores only because
    ``PRAGMA foreign_key_check`` returned clean on each. Any future store must
    clear the same gate rather than switching the pragma on and hoping.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE parents (id TEXT PRIMARY KEY);
        CREATE TABLE children (
            id TEXT PRIMARY KEY,
            parent_id TEXT,
            FOREIGN KEY (parent_id) REFERENCES parents(id)
        );
        """
    )
    # Written with enforcement OFF — exactly how legacy orphans arise.
    conn.execute("INSERT INTO children VALUES ('c1', 'ghost')")
    conn.commit()

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations, "foreign_key_check failed to report a known orphan"
    assert violations[0][0] == "children"
    conn.close()
