"""Tests for default system routines and cron scheduling in ARES."""

from __future__ import annotations

from pathlib import Path
import pytest

from api.schedule_jobs import ensure_system_routines, list_jobs, create_job, remove_job


def test_ensure_system_routines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify ensure_system_routines registers default jobs into jobs.json."""
    ares_dir = tmp_path / ".ares"
    monkeypatch.setattr("api.schedule_jobs.ARES_DIR", ares_dir)
    monkeypatch.setattr("api.schedule_jobs.CRON_DIR", ares_dir / "cron")
    monkeypatch.setattr("api.schedule_jobs.JOBS_FILE", ares_dir / "cron" / "jobs.json")
    monkeypatch.setattr("api.schedule_jobs.OUTPUT_DIR", ares_dir / "cron" / "output")

    created = ensure_system_routines()
    assert len(created) == 2
    names = {c["name"] for c in created}
    assert "Cross-Agent Memory Synchronization" in names
    assert "Local Model Orchestrator Evaluation Probe" in names

    # Idempotence: running again should create 0 new jobs
    created_second = ensure_system_routines()
    assert len(created_second) == 0

    all_jobs = list_jobs()
    assert len(all_jobs) == 2
