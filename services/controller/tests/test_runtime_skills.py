from __future__ import annotations


def _contract():
    return {
        "negotiated": True,
        "error": None,
        "runtime_contract": {
            "features": {"skills": {"available": True, "owner": "jaeger", "mutable": True}},
        },
    }


def test_runtime_skill_queries_are_contract_gated_and_normalized(monkeypatch):
    from api import ares_capabilities, runtime_skills
    from api.providers.jaeger import streaming

    monkeypatch.setattr(ares_capabilities, "capability_contract_for_backend", lambda _backend: _contract())
    monkeypatch.setattr(streaming, "query_local_companion", lambda what, args: {
        "skills": [
            {"name": "deploy", "category": "ops"},
            {"name": "summarize", "category": "research"},
        ],
        "owner": "jaeger",
    })

    result = runtime_skills.list_runtime_skills("ops")
    assert result == {"skills": [{"name": "deploy", "category": "ops"}], "owner": "jaeger"}


def test_runtime_skill_mutations_use_jaeger_commands(monkeypatch):
    from api import ares_capabilities, runtime_skills
    from api.providers.jaeger import streaming

    calls = []
    monkeypatch.setattr(ares_capabilities, "capability_contract_for_backend", lambda _backend: _contract())
    monkeypatch.setattr(
        streaming,
        "command_local_companion",
        lambda command, args: calls.append((command, args)) or {"ok": True},
    )

    runtime_skills.install_runtime_skill("custom", "---\nname: custom\n---\n", "ops")
    runtime_skills.clone_runtime_skill("builtin")
    runtime_skills.toggle_runtime_skill("custom", False)
    runtime_skills.toggle_runtime_skill("custom", True)
    runtime_skills.remove_runtime_skill("custom")

    assert [call[0] for call in calls] == [
        "install_skill", "clone_skill", "disable_skill", "enable_skill", "remove_skill",
    ]


def test_runtime_skills_fail_closed_without_negotiated_support(monkeypatch):
    import pytest

    from api import ares_capabilities, runtime_skills

    monkeypatch.setattr(ares_capabilities, "capability_contract_for_backend", lambda _backend: {
        "negotiated": False,
        "error": "contract mismatch",
        "runtime_contract": None,
    })

    with pytest.raises(runtime_skills.RuntimeSkillError, match="contract mismatch") as caught:
        runtime_skills.list_runtime_skills()
    assert caught.value.status_code == 503


def test_runtime_skills_reject_traversal_before_calling_jaeger(monkeypatch):
    import pytest

    from api import ares_capabilities, runtime_skills
    from api.providers.jaeger import streaming

    monkeypatch.setattr(
        ares_capabilities, "capability_contract_for_backend", lambda _backend: _contract()
    )
    called = []
    monkeypatch.setattr(
        streaming,
        "command_local_companion",
        lambda *args: called.append(args),
    )
    with pytest.raises(runtime_skills.RuntimeSkillError) as caught:
        runtime_skills.install_runtime_skill("../../outside", "bad")
    assert caught.value.status_code == 400
    with pytest.raises(runtime_skills.RuntimeSkillError) as caught:
        runtime_skills.get_runtime_skill("safe", "../../etc/passwd")
    assert caught.value.status_code == 400
    assert called == []
