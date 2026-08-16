from __future__ import annotations


def test_enable_configures_and_reloads_through_jaeger(monkeypatch):
    from api import ares_tools_mcp

    calls = []
    monkeypatch.setattr(ares_tools_mcp, "_server_config",
                        lambda: {"command": "/python", "args": ["/mcp_server.py"], "enabled": True})
    monkeypatch.setattr(ares_tools_mcp, "_command",
                        lambda command, args: calls.append((command, args)) or {"ok": True})
    monkeypatch.setattr(ares_tools_mcp, "ares_tools_status",
                        lambda: {"available": True, "enabled": True, "active": True})

    result = ares_tools_mcp.set_ares_tools_enabled(True)
    assert result["active"] is True
    assert calls == [
        ("configure_mcp_server", {"name": "ares-controller", "config": {
            "command": "/python", "args": ["/mcp_server.py"], "enabled": True,
        }}),
        ("reload_tools", {}),
    ]


def test_disable_is_idempotent_when_server_is_absent(monkeypatch):
    from api import ares_tools_mcp
    monkeypatch.setattr(ares_tools_mcp, "ares_tools_status",
                        lambda: {"available": True, "enabled": False, "active": False, "server": None})
    assert ares_tools_mcp.set_ares_tools_enabled(False) == {
        "ok": True, "enabled": False, "active": False,
    }
