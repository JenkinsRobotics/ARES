"""Cron liveness must be stamped onto session-list rows.

The sidebar polls /api/sessions (never /api/crons/status), so a still-running
job's row must carry ``cron_running=True`` until the callback returns.
"""

from __future__ import annotations


def _cron_row(session_id: str, created_at: float) -> dict:
    return {
        "session_id": session_id,
        "created_at": created_at,
        "updated_at": created_at,
        "last_message_at": created_at,
        "message_count": 1,
    }


def test_overlay_stamps_ares_and_jaeger_running_jobs(monkeypatch):
    import api.route_session_list_cache as slc

    monkeypatch.setattr(
        slc,
        "_session_list_cache_running_cron_jobs",
        lambda: {"job6728": 1000.0, "morning": 2000.0},
    )
    monkeypatch.setattr(slc, "_session_list_cache_active_stream_ids", lambda: set())

    rows = slc._session_list_cache_overlay_runtime_rows(
        [
            _cron_row("cron_job6728_20260803_100000", created_at=1100),
            _cron_row("cron:morning", created_at=2100),
            _cron_row("regular-chat", created_at=3000),
            _cron_row("cron_job6728_20260701_050000", created_at=500),
        ]
    )
    by_sid = {row["session_id"]: row for row in rows}
    assert by_sid["cron_job6728_20260803_100000"]["cron_running"] is True
    assert by_sid["cron:morning"]["cron_running"] is True
    assert by_sid["regular-chat"]["cron_running"] is False
    assert by_sid["cron_job6728_20260701_050000"]["cron_running"] is False


def test_overlay_fails_closed_when_no_running_jobs(monkeypatch):
    import api.route_session_list_cache as slc

    monkeypatch.setattr(slc, "_session_list_cache_running_cron_jobs", lambda: {})
    monkeypatch.setattr(slc, "_session_list_cache_active_stream_ids", lambda: set())

    rows = slc._session_list_cache_overlay_runtime_rows(
        [_cron_row("cron_job6728_20260803_100000", created_at=1100)]
    )
    assert rows[0]["cron_running"] is False


def test_shorter_running_job_cannot_claim_longer_job_session(monkeypatch):
    import api.route_session_list_cache as slc

    monkeypatch.setattr(
        slc, "_session_list_cache_running_cron_jobs", lambda: {"backup": 1000.0}
    )
    monkeypatch.setattr(slc, "_session_list_cache_active_stream_ids", lambda: set())

    rows = slc._session_list_cache_overlay_runtime_rows(
        [
            _cron_row("cron_backup_20260803_100000", created_at=1100),
            _cron_row("cron_backup_full_20260803_210000", created_at=2100),
        ]
    )
    by_sid = {row["session_id"]: row for row in rows}
    assert by_sid["cron_backup_20260803_100000"]["cron_running"] is True
    assert by_sid["cron_backup_full_20260803_210000"]["cron_running"] is False
