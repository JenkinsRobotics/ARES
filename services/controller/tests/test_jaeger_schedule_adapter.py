"""ARES cron panel maps Jaeger schedule rows, not a Hermes gateway."""

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from integrations.providers.jaeger.schedules import _job_from_jaeger


def test_jaeger_row_becomes_webui_job():
    job = _job_from_jaeger({
        "name": "morning",
        "cron": "30 7 * * *",
        "prompt": "brief me",
        "next_run_at": "2026-08-21T12:00:00+00:00",
        "status": "active",
        "paused": False,
    })
    assert job["id"] == "morning"
    assert job["schedule"] == "30 7 * * *"
    assert job["enabled"] is True
    assert job["owner"] == "jaeger"


def test_paused_row_is_not_enabled():
    job = _job_from_jaeger({"name": "x", "cron": "@once", "status": "paused", "paused": True})
    assert job["paused"] is True
    assert job["enabled"] is False
