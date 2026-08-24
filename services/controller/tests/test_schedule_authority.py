"""Single-authority schedule catalog.

Phase 0.5 finding: ARES ``~/.ares/cron/jobs.json`` and JaegerAI schedules
were both writable, but ``list_schedules`` preferred Jaeger exclusively
when the agent was up. A create that fell back locally then vanished
from list. That is split-brain.

The rule now:

  * CREATE writes one store. If Jaeger is available and refuses, the
    error is returned — no silent local write.
  * LIST is a projection: Jaeger jobs (owner=jaeger) plus leftover
    local jobs (owner=ares_local) so existing ARES jobs stay visible.
  * UPDATE/DELETE follow the owner of that id.
"""

from __future__ import annotations

import pytest


def test_create_appears_in_list_when_jaeger_is_down(monkeypatch):
    from api import schedules_store as store

    saved: dict = {"jobs": []}

    def _create(payload):
        job = {
            "id": "local-new",
            "name": payload["name"],
            "prompt": payload["prompt"],
            "schedule": payload["schedule"],
        }
        saved["jobs"] = [job]
        return job

    monkeypatch.setattr(store, "_jaeger_jobs", lambda: None)
    monkeypatch.setattr(
        "api.providers.jaeger.schedules.runtime_status",
        lambda: {"available": False},
    )
    monkeypatch.setattr("api.schedule_jobs.create_job", lambda **kw: _create(kw))
    monkeypatch.setattr(
        store,
        "_local_schedule_payload",
        lambda all_profiles=False: {"jobs": list(saved["jobs"]), "other_profile_count": 0},
    )

    created = store.create_schedule({
        "prompt": "weekly brief",
        "schedule": "0 18 * * 6",
        "name": "weekly-brief-generator",
    })
    assert created["ok"] is True
    listed = store.list_schedules()
    assert any(row["id"] == "local-new" for row in listed["jobs"])
    match = next(row for row in listed["jobs"] if row["id"] == "local-new")
    assert match["owner"] == "ares_local"


def test_failed_jaeger_create_does_not_write_locally(monkeypatch):
    from api import schedules_store as store
    from api.providers.jaeger.schedules import JaegerScheduleError

    local_writes: list = []
    monkeypatch.setattr(
        "api.providers.jaeger.schedules.runtime_status",
        lambda: {"available": True},
    )

    def _refuse(_payload):
        raise JaegerScheduleError(
            "confirmation refused for scheduling.schedule_prompt (tier WRITE_LOCAL)",
            403,
        )

    monkeypatch.setattr("api.providers.jaeger.schedules.create_job", _refuse)
    monkeypatch.setattr(
        "api.schedule_jobs.create_job",
        lambda **kw: local_writes.append(kw) or kw,
    )

    with pytest.raises(store.ScheduleStoreError, match="refused"):
        store.create_schedule({
            "prompt": "should not land locally",
            "schedule": "0 0 * * *",
            "name": "ghost-job",
        })
    assert local_writes == []


def test_list_keeps_local_jobs_visible_when_jaeger_is_up(monkeypatch):
    from api import schedules_store as store

    monkeypatch.setattr(
        store,
        "_jaeger_jobs",
        lambda: [{"id": "jaeger-1", "name": "jaeger-1", "prompt": "si", "schedule": "0 9 * * *"}],
    )
    monkeypatch.setattr(
        store,
        "_local_schedule_payload",
        lambda all_profiles=False: {
            "jobs": [{
                "id": "a76b58e04dd440f1",
                "name": "Local Model Orchestrator Evaluation Probe",
                "prompt": "probe",
                "schedule": "0 0 * * *",
            }],
            "other_profile_count": 0,
        },
    )

    listed = store.list_schedules()
    by_name = {row["name"]: row["owner"] for row in listed["jobs"]}
    assert by_name["jaeger-1"] == "jaeger"
    assert by_name["Local Model Orchestrator Evaluation Probe"] == "ares_local"
    assert listed["compatibility_job_count"] == 1


def test_delete_of_jaeger_job_does_not_remove_a_local_namesake(monkeypatch):
    from api import schedules_store as store

    cancelled: list[str] = []
    removed: list[str] = []

    monkeypatch.setattr(
        store,
        "_jaeger_jobs",
        lambda: [{"id": "weekly-brief-generator", "name": "weekly-brief-generator",
                  "prompt": "si", "schedule": "0 18 * * 6"}],
    )
    monkeypatch.setattr(
        store,
        "_local_schedule_payload",
        lambda all_profiles=False: {
            "jobs": [{
                "id": "efa6e9009cfd49af",
                "name": "weekly-brief-generator-local",
                "prompt": "keep me",
                "schedule": "0 18 * * 6",
            }],
            "other_profile_count": 0,
        },
    )
    monkeypatch.setattr(
        "api.providers.jaeger.schedules.cancel_job",
        lambda job_id: cancelled.append(job_id),
    )
    monkeypatch.setattr(
        "api.schedule_jobs.remove_job",
        lambda job_id: removed.append(job_id) or True,
    )

    result = store.delete_schedule("weekly-brief-generator")
    assert result["owner"] == "jaeger"
    assert cancelled == ["weekly-brief-generator"]
    assert removed == []
