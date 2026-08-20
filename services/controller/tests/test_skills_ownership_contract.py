"""Deterministic cover for the Jaeger-owned Skills branch of /api/skills.

``tests/test_sprint7.py`` drives a real out-of-process server over HTTP, so it
cannot stub which owner answers ``/api/skills/save`` — the branch is decided by
``selected_runtime_owns_skills()`` reading the running server's active backend.
That made the strong assertion ("Jaeger answers, and Ares never writes a file")
environment-dependent: it held only on a machine with a Skills-capable Jaeger
runtime, and failed on CI with ``assert None == 'jaeger'``.

These tests call the router in-process so the ownership decision and the bridge
call can both be stubbed. That pins the part that actually matters — the
ownership boundary — on every machine, including CI, with no Jaeger runtime
present.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fastapi_app.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def jaeger_owns_skills(monkeypatch):
    """Route /api/skills through the Jaeger bridge with the runtime stubbed.

    Patches the names the router imports at call time (``api.runtime_skills``),
    so no live companion process, contract negotiation, or network is involved.
    Returns the list of calls the router forwarded, so a test can assert Ares
    delegated rather than acting locally.
    """
    import api.runtime_skills as runtime_skills

    forwarded: list[tuple[str, tuple, dict]] = []

    def _install(name, content, category=""):
        forwarded.append(("install", (name, content, category), {}))
        # Shape the real bridge returns: the owner and the skill name, never a
        # local filesystem path.
        return {"ok": True, "name": name, "owner": "jaeger"}

    def _remove(name):
        forwarded.append(("remove", (name,), {}))
        return {"ok": True, "name": name, "owner": "jaeger"}

    monkeypatch.setattr(runtime_skills, "selected_runtime_owns_skills", lambda: True)
    monkeypatch.setattr(runtime_skills, "install_runtime_skill", _install)
    monkeypatch.setattr(runtime_skills, "remove_runtime_skill", _remove)
    return forwarded


SKILL = "test-ownership-contract-skill"
CONTENT = "---\nname: test-ownership-contract-skill\ndescription: QA.\n---\n\n# Test\n"


def test_save_reports_jaeger_as_owner_and_never_a_local_path(client, jaeger_owns_skills):
    res = client.post("/api/skills/save", json={"name": SKILL, "content": CONTENT})
    assert res.status_code == 200
    body = res.json()
    assert body.get("ok") is True
    assert body.get("owner") == "jaeger"
    assert body.get("name") == SKILL
    # The load-bearing assertion: a path here would mean Ares wrote the skill
    # file itself while reporting that Jaeger owns it.
    assert "path" not in body


def test_save_delegates_to_the_runtime_rather_than_writing_locally(client, jaeger_owns_skills):
    client.post("/api/skills/save", json={"name": SKILL, "content": CONTENT})
    assert [call[0] for call in jaeger_owns_skills] == ["install"]
    assert jaeger_owns_skills[0][1][0] == SKILL
    assert jaeger_owns_skills[0][1][1] == CONTENT


def test_delete_delegates_to_the_runtime(client, jaeger_owns_skills):
    res = client.post("/api/skills/delete", json={"name": SKILL})
    assert res.status_code == 200
    assert res.json().get("ok") is True
    assert [call[0] for call in jaeger_owns_skills] == ["remove"]


def test_absent_skill_is_a_404_not_a_gateway_error(client, monkeypatch):
    """A named-but-absent skill is a client error, not an outage (0b938d59).

    ``_command`` used to map every bridge exception to 502, making a typo
    indistinguishable from the runtime being down.
    """
    import api.runtime_skills as runtime_skills
    from api.runtime_skills import RuntimeSkillError

    def _missing(name):
        raise RuntimeSkillError(f"no such skill: {name}", 404)

    monkeypatch.setattr(runtime_skills, "selected_runtime_owns_skills", lambda: True)
    monkeypatch.setattr(runtime_skills, "remove_runtime_skill", _missing)

    res = client.post("/api/skills/delete", json={"name": "definitely-not-a-skill-xyz"})
    assert res.status_code == 404
