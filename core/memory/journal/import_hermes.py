"""
ARES Journal — Hermes Agent importer.

Reads all sessions and messages from the Hermes state.db SQLite database
and imports them into the unified ARES journal.
"""

import json
import sqlite3
import time
from typing import Optional

from .paths import hermes_db
from .schema import get_db, init_db


def import_hermes(batch_id: str, since: Optional[float] = None) -> dict:
    """
    Import all Hermes sessions and messages into the journal.

    Args:
        batch_id: UUID for this import run.
        since: Optional unix timestamp to only import sessions updated after this time.

    Returns:
        Dict with import statistics.
    """
    db_path = hermes_db()
    if not db_path.exists():
        return {
            "source": "hermes",
            "imported_conversations": 0,
            "imported_messages": 0,
            "skipped": True,
            "reason": f"{db_path} not found",
        }

    try:
        src = sqlite3.connect(str(db_path))
        src.row_factory = sqlite3.Row
        jdb = init_db()

        # Check if sessions table exists
        has_table = src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()
        if not has_table:
            src.close()
            return {
                "source": "hermes",
                "imported_conversations": 0,
                "imported_messages": 0,
                "skipped": True,
                "reason": "sessions table not found in hermes state.db",
            }

        sql = """
            SELECT id, source, title, model, cwd, started_at, ended_at,
                   message_count, tool_call_count, input_tokens, output_tokens,
                   git_branch, git_repo_root, display_name, chat_id, chat_type
            FROM sessions
        """
        params: list = []
        if since:
            sql += " WHERE started_at > ?"
            params.append(since)

        sessions = src.execute(sql, params).fetchall()

        conv_imported = 0
        msg_imported = 0

        for sess in sessions:
            existing = jdb.execute(
                "SELECT id FROM conversations WHERE source = 'hermes' AND session_id = ?",
                (str(sess["id"]),),
            ).fetchone()

            if existing:
                continue

            jdb.execute(
                """INSERT OR IGNORE INTO conversations
                   (source, session_id, title, model, workspace, created_at, updated_at,
                    message_count, source_path, import_batch, import_ts, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "hermes",
                    str(sess["id"]),
                    sess["title"] or sess["display_name"] or "Hermes Session",
                    sess["model"] or "",
                    sess["cwd"] or "",
                    sess["started_at"] or time.time(),
                    sess["ended_at"] or sess["started_at"] or time.time(),
                    sess["message_count"] or 0,
                    str(db_path),
                    batch_id,
                    time.time(),
                    json.dumps({
                        "source_type": sess["source"],
                        "chat_id": sess["chat_id"],
                        "chat_type": sess["chat_type"],
                        "tool_call_count": sess["tool_call_count"],
                        "input_tokens": sess["input_tokens"],
                        "output_tokens": sess["output_tokens"],
                        "git_branch": sess["git_branch"],
                        "git_repo_root": sess["git_repo_root"],
                    }),
                ),
            )
            conv_row = jdb.execute(
                "SELECT id FROM conversations WHERE source = 'hermes' AND session_id = ?",
                (str(sess["id"]),),
            ).fetchone()
            if not conv_row:
                continue
            conv_id = conv_row["id"]

            # Check messages table
            has_msg_table = src.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
            ).fetchone()

            if has_msg_table:
                msgs = src.execute(
                    """SELECT id, session_id, role, content, tool_name, tool_calls,
                              timestamp, token_count, finish_reason, reasoning_content
                       FROM messages
                       WHERE session_id = ? AND (active IS NULL OR active = 1)
                       ORDER BY timestamp""",
                    (sess["id"],),
                ).fetchall()

                for seq, msg in enumerate(msgs):
                    content = (msg["content"] or "")[:100000]
                    jdb.execute(
                        """INSERT INTO messages
                           (conversation_id, seq, role, content, timestamp, model,
                            tool_name, token_count, metadata)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            conv_id,
                            seq,
                            msg["role"] or "user",
                            content,
                            msg["timestamp"] or time.time(),
                            sess["model"] or "",
                            msg["tool_name"] or None,
                            msg["token_count"] or 0,
                            json.dumps({
                                "finish_reason": msg["finish_reason"],
                                "has_reasoning": bool(msg["reasoning_content"]),
                                "has_tool_calls": bool(msg["tool_calls"]),
                            }),
                        ),
                    )
                    msg_imported += 1

            conv_imported += 1

        jdb.commit()
        src.close()

        return {
            "source": "hermes",
            "imported_conversations": conv_imported,
            "imported_messages": msg_imported,
            "skipped": False,
        }
    except Exception as exc:
        return {
            "source": "hermes",
            "imported_conversations": 0,
            "imported_messages": 0,
            "skipped": True,
            "reason": str(exc),
        }
