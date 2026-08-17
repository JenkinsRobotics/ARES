from __future__ import annotations

import importlib


class _Backend:
    def __init__(self, text):
        self.text = text

    def is_available(self):
        return True

    def run_turn(self, prompt, session_id, **_kwargs):
        return {"text": f"{self.text}:{prompt}", "error": None}


class _Router:
    def __init__(self):
        self.backends = {"small": _Backend("small"), "teacher": _Backend("teacher")}

    def select(self, name):
        return self.backends.get(name)

    def list_all(self):
        return self.backends


def test_compare_uses_backend_router_and_persists_results(tmp_path, monkeypatch):
    from api import model_intelligence

    model_intelligence = importlib.reload(model_intelligence)
    monkeypatch.setattr(
        "api.profiles.get_ares_home_for_profile", lambda _profile: tmp_path
    )
    monkeypatch.setattr("api.backends.router.get_router", lambda: _Router())
    result = model_intelligence.compare(
        "work", prompt="explain", targets=[{"backend": "small"}, {"backend": "teacher"}]
    )
    assert [item["backend"] for item in result["results"]] == ["small", "teacher"]
    assert model_intelligence.history("work")["runs"][0]["id"] == result["id"]
    assert model_intelligence._runs_path("work").stat().st_mode & 0o777 == 0o600


def test_teacher_only_escalates_failed_primary(tmp_path, monkeypatch):
    from api import model_intelligence

    monkeypatch.setattr(
        "api.profiles.get_ares_home_for_profile", lambda _profile: tmp_path
    )
    calls = []

    def execute(target, _prompt, _run_id):
        calls.append(target["backend"])
        return {
            "backend": target["backend"],
            "evaluation": {"verdict": "fail" if len(calls) == 1 else "pass"},
        }

    monkeypatch.setattr(model_intelligence, "_execute", execute)
    result = model_intelligence.teacher_escalation(
        "work",
        prompt="hard",
        primary={"backend": "small"},
        teacher={"backend": "teacher"},
    )
    assert result["escalated"] is True
    assert calls == ["small", "teacher"]


def test_cookbook_reuses_hatchery_instead_of_shell_commands():
    from api.model_intelligence import recipes

    hatchery = next(recipe for recipe in recipes() if recipe["kind"] == "model_serving")
    assert hatchery["routes"] == [
        "/api/hatchery/scan",
        "/api/hatchery/mold",
        "/api/hatchery/hatch",
    ]
    assert "command" not in hatchery
