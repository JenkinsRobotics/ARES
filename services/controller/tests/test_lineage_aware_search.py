from types import SimpleNamespace

from api.session_query import search_sessions


def test_match_in_hidden_child_returns_one_lineage_result(monkeypatch):
    rows = [
        {"session_id": "root", "title": "Mission", "profile": "default", "updated_at": "1"},
        {"session_id": "child", "title": "Continuation", "profile": "default", "parent_session_id": "root", "updated_at": "2"},
        {"session_id": "grandchild", "title": "Tip", "profile": "default", "parent_session_id": "child", "updated_at": "3"},
    ]
    messages = {
        "root": [], "child": [{"role": "assistant", "content": "the unique needle is here"}], "grandchild": [],
    }
    monkeypatch.setattr("api.models.all_sessions", lambda: rows)
    monkeypatch.setattr("api.models.get_session", lambda sid: SimpleNamespace(messages=messages[sid]))
    monkeypatch.setattr("api.profiles.get_active_profile_name", lambda: "default")
    monkeypatch.setattr("api.delegation_tasks.list_tasks", lambda: [])

    result = search_sessions("needle", depth=0, lineage=True)
    assert result["count"] == 1
    item = result["sessions"][0]
    assert item["lineage_root_id"] == "root"
    assert item["session_id"] == "grandchild"
    assert item["lineage_tip_id"] == "grandchild"
    assert item["lineage_match_session_ids"] == ["child"]
    assert set(item["lineage_session_ids"]) == {"root", "child", "grandchild"}
    assert item["lineage_size"] == 3


def test_delegated_task_results_are_searchable_with_lineage(monkeypatch):
    monkeypatch.setattr("api.models.all_sessions", lambda: [])
    monkeypatch.setattr("api.profiles.get_active_profile_name", lambda: "default")
    monkeypatch.setattr("api.delegation_tasks.list_tasks", lambda: [{
        "id": "task-child", "root_task_id": "task-root", "parent_task_id": "task-root",
        "parent_session_id": "session-root", "relation": "delegated", "status": "completed",
        "prompt": "research", "result": "found the unique needle", "error": None,
    }])
    result = search_sessions("needle", lineage=True)
    assert result["sessions"] == []
    assert result["delegated_tasks"][0]["root_task_id"] == "task-root"
    assert "needle" in result["delegated_tasks"][0]["match_preview"]
