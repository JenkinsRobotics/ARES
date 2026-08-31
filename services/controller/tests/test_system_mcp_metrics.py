from __future__ import annotations

import system_mcp_server as system_mcp


def test_system_metrics_uses_existing_authenticated_stats_endpoint(monkeypatch):
    seen = {}

    def request(method, path, payload=None):
        seen.update(method=method, path=path, payload=payload)
        return {"ok": True, "host": {"top_processes": []}}

    monkeypatch.setattr(system_mcp, "_request", request)

    result = system_mcp.system_metrics(include_processes=True, process_limit=100)

    assert result["ok"] is True
    assert seen["method"] == "GET"
    assert "include_processes=true" in seen["path"]
    assert "process_limit=25" in seen["path"]
    assert seen["payload"] is None


def test_system_mcp_labels_inspection_and_effect_tools_honestly():
    tools = system_mcp.mcp._tool_manager._tools

    for name in ("system_status", "system_metrics", "agents_list", "integrations_list", "run_status", "approval_preview"):
        annotations = tools[name].annotations
        assert annotations.read_only_hint is True
        assert annotations.destructive_hint is False

    for name in ("run_cancel", "approval_respond"):
        annotations = tools[name].annotations
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is True
