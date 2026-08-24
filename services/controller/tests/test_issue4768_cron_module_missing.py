"""ARES schedule storage stays a working fallback when JaegerAI is not there.

Issue 4768 was "cron module missing": ``list_schedules`` could return
``{"cron_unavailable": True}`` instead of reading the internal store, so the
jobs panel showed nothing and the operator had no way to tell a broken import
from an empty schedule.

Since then, ownership moved: ``e7e4ec986 feat(crons): run scheduled jobs
through JaegerAI, not a Hermes gateway``. ``list_schedules`` now delegates to
JaegerAI whenever ``runtime_status()`` reports available, and only falls back to
``api.schedule_jobs`` when it does not. The original test asserted the internal
module was used unconditionally, which stopped being true — and on a machine
with a live agent it read JaegerAI's real schedules, so it reported the
operator's actual jobs as a failure.

These tests pin the contract that actually exists, on both sides of the
delegation, and the fallback keeps the 4768 guarantee it was written for.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def internal_store(monkeypatch, tmp_path):
    """Force the fallback path and give it an isolated home.

    ``_jaeger_jobs`` returning None is exactly what "JaegerAI is not available"
    looks like to ``list_schedules`` — stubbing it is how the fallback gets
    exercised deterministically instead of depending on whether the developer's
    agent happens to be running.
    """
    monkeypatch.setattr("api.schedules_store._jaeger_jobs", lambda: None)
    monkeypatch.setattr("api.profiles.get_active_profile_name", lambda: "default")
    monkeypatch.setattr("api.profiles.get_ares_home_for_profile", lambda _profile: tmp_path)
    monkeypatch.setattr("api.profiles.list_profiles_api", lambda: [])
    return tmp_path


def test_the_internal_store_is_used_when_jaeger_is_unavailable(internal_store):
    """The 4768 guarantee: a missing agent is not a missing cron module."""
    import api.schedule_jobs as jobs
    from api.profiles import cron_profile_context_for_home
    from api.schedules_store import list_schedules

    with cron_profile_context_for_home(internal_store):
        jobs.create_job(prompt="internal", schedule="0 9 * * *")
        result = list_schedules()

    assert "cron_unavailable" not in result, (
        "the internal schedule module was reported missing while it was working"
    )
    prompts = [job.get("prompt") for job in result["jobs"]]
    assert "internal" in prompts, f"the created job was not listed: {prompts}"
    assert result.get("owner") != "jaeger"


def test_jaeger_owns_the_list_when_it_is_available(monkeypatch):
    """The other half — otherwise a broken delegation would look like success.

    Without this, ``_jaeger_jobs`` could start returning None permanently and
    the test above would still pass while the product silently stopped showing
    the schedules JaegerAI actually runs.
    """
    from api import schedules_store

    monkeypatch.setattr(
        schedules_store, "_jaeger_jobs",
        lambda: [{"id": "j1", "prompt": "from jaeger", "schedule": "0 9 * * *"}],
    )
    monkeypatch.setattr("api.profiles.get_active_profile_name", lambda: "default")

    result = schedules_store.list_schedules()

    assert result["owner"] == "jaeger"
    assert [job.get("prompt") for job in result["jobs"]] == ["from jaeger"]
    assert "cron_unavailable" not in result


def test_a_jaeger_failure_falls_back_rather_than_reporting_no_cron(monkeypatch, tmp_path):
    """A raising delegate must degrade to the internal store, not to nothing.

    ``_jaeger_jobs`` swallows its own exceptions and returns None, which is the
    behaviour that makes the fallback reachable. Pinned because a future change
    that let the exception escape would surface as an empty jobs panel rather
    than as an error anybody notices.
    """
    from api.providers.jaeger import schedules as jaeger_schedules
    from api.schedules_store import _jaeger_jobs

    def _boom():
        raise RuntimeError("bridge is down")

    monkeypatch.setattr(jaeger_schedules, "runtime_status", _boom)
    assert _jaeger_jobs() is None


def test_the_cron_profile_context_is_reentrant(tmp_path):
    """Regression: nesting the context on one thread used to deadlock outright.

    ``list_schedules`` enters ``cron_profile_context_for_home`` once per profile
    while resolving the internal store. A caller that already held it — the
    background thread behind ``/api/crons/run``, which is precisely what this
    ``_for_home`` variant is documented for — re-entered on the same thread and
    blocked forever on a non-reentrant ``threading.Lock``.

    The thread-local depth counter beside the lock shows nesting was always
    intended; only the lock type withheld it. No timeout is needed: if this
    regresses, the test hangs, which is the same symptom the product had.
    """
    import os

    from api.profiles import cron_profile_context_for_home

    outer = tmp_path / "outer"
    inner = tmp_path / "inner"
    outer.mkdir()
    inner.mkdir()

    with cron_profile_context_for_home(outer):
        assert os.environ["ARES_HOME"] == str(outer)
        with cron_profile_context_for_home(inner):
            assert os.environ["ARES_HOME"] == str(inner)
        # Unwinding must restore the OUTER home, not the pre-outer one.
        assert os.environ["ARES_HOME"] == str(outer), (
            "leaving the inner context did not restore the outer profile home"
        )


# ── create/list ownership consistency ──────────────────────────────────


def test_a_refused_jaeger_create_is_an_error_not_a_silent_local_write(monkeypatch):
    """The live split-brain, pinned.

    JaegerAI owns scheduling whenever it is running, and refuses
    ``scheduling.schedule_prompt`` on an API call because it is a tier-2 tool
    with no confirmer attached. ``create_schedule`` used to catch that, write
    the job into the LOCAL store, and return ``ok: True`` — while
    ``list_schedules`` went on returning Jaeger's list, because Jaeger was
    available. The job existed and could never be seen again.

    Falling back is still right when Jaeger is simply DOWN (the test below);
    it is wrong when Jaeger is up and saying no.
    """
    from api import schedules_store
    from api.providers.jaeger import schedules as jaeger_schedules

    monkeypatch.setattr(jaeger_schedules, "runtime_status", lambda: {"available": True})

    def _refused(_payload):
        raise RuntimeError(
            "confirmation refused for scheduling.schedule_prompt (tier WRITE_LOCAL)"
        )

    monkeypatch.setattr(jaeger_schedules, "create_job", _refused)

    with pytest.raises(schedules_store.ScheduleStoreError) as caught:
        schedules_store.create_schedule(
            {"name": "probe", "schedule": "0 9 * * *", "prompt": "p", "deliver": "local"}
        )
    message = str(caught.value)
    assert "refused" in message
    assert "permission" in message, "the operator is not told how to fix it"


def test_a_down_jaeger_still_falls_back_to_the_local_store(monkeypatch, tmp_path):
    """The other side: an absent agent must not block scheduling.

    Without this, the fix above would look correct while having turned every
    agent-less install into one that cannot create a schedule at all.
    """
    from api import schedules_store
    from api.providers.jaeger import schedules as jaeger_schedules
    from api.profiles import cron_profile_context_for_home

    monkeypatch.setattr(jaeger_schedules, "runtime_status", lambda: {"available": False})
    monkeypatch.setattr("api.profiles.get_active_profile_name", lambda: "default")
    monkeypatch.setattr("api.profiles.get_ares_home_for_profile", lambda _p: tmp_path)
    monkeypatch.setattr("api.profiles.list_profiles_api", lambda: [])

    with cron_profile_context_for_home(tmp_path):
        result = schedules_store.create_schedule(
            {"name": "local-probe", "schedule": "0 9 * * *", "prompt": "p",
             "deliver": "local"}
        )
        assert result["ok"] is True
        listed = schedules_store.list_schedules()

    names = [job.get("name") for job in listed["jobs"]]
    assert "local-probe" in names, (
        f"a job created against the local store was not listed back: {names}"
    )
