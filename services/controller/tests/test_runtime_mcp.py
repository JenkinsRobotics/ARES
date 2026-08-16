from __future__ import annotations

import pytest


def _contract(available=True):
    return {"negotiated": True, "error": None,
            "runtime_contract": {"features": {"mcp_server_config": {"available": available}}}}


def test_runtime_mcp_queries_and_commands(monkeypatch):
    from api import ares_capabilities, runtime_mcp
    from api.providers.jaeger import gateway_streaming
    calls = []
    monkeypatch.setattr(ares_capabilities, "capability_contract_for_backend", lambda _backend: _contract())
    monkeypatch.setattr(gateway_streaming, "query_local_companion",
                        lambda what, args: {"tools": [], "total": 0, "unavailable_servers": []})
    monkeypatch.setattr(gateway_streaming, "command_local_companion",
                        lambda cmd, args: calls.append((cmd, args)) or {"ok": True})

    assert runtime_mcp.list_runtime_tools()["total"] == 0
    runtime_mcp.configure_runtime_server("web", {"command": "uvx"})
    runtime_mcp.toggle_runtime_server("web", False)
    runtime_mcp.toggle_runtime_server("web", True)
    runtime_mcp.remove_runtime_server("web")
    runtime_mcp.reload_runtime_tools()
    assert [row[0] for row in calls] == ["configure_mcp_server", "disable_mcp_server",
                                         "enable_mcp_server", "remove_mcp_server", "reload_tools"]


def test_runtime_mcp_fails_closed(monkeypatch):
    from api import ares_capabilities, runtime_mcp
    monkeypatch.setattr(ares_capabilities, "capability_contract_for_backend",
                        lambda _backend: {"negotiated": False, "error": "contract mismatch",
                                          "runtime_contract": None})
    with pytest.raises(runtime_mcp.RuntimeMCPError, match="contract mismatch") as caught:
        runtime_mcp.list_runtime_servers()
    assert caught.value.status_code == 503
