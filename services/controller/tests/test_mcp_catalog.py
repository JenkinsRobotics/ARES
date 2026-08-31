"""Tests for ARES MCP server and tool catalog."""

from __future__ import annotations

from api.mcp_catalog import get_mcp_catalog


def test_mcp_catalog_structure():
    catalog = get_mcp_catalog()
    assert catalog["ok"] is True
    assert catalog["total_servers"] >= 4
    assert catalog["total_tools"] >= 50
    assert "servers" in catalog
    assert "gateway" in catalog

    server_ids = {s["id"] for s in catalog["servers"]}
    assert "ares-system" in server_ids
    assert "ares-host" in server_ids
    assert "ares-webui" in server_ids

    # Verify ares-system has system_metrics and system_status
    ares_system = next(s for s in catalog["servers"] if s["id"] == "ares-system")
    sys_tool_names = {t["name"] for t in ares_system["tools"]}
    assert "system_status" in sys_tool_names
    assert "system_metrics" in sys_tool_names
    assert "approval_respond" in sys_tool_names

    # Verify ares-host has camera tools
    ares_host = next(s for s in catalog["servers"] if s["id"] == "ares-host")
    host_tool_names = {t["name"] for t in ares_host["tools"]}
    assert "camera_status" in host_tool_names
    assert "camera_snapshot" in host_tool_names
    assert "camera_listen" in host_tool_names
    assert "camera_ptz" in host_tool_names
    assert "workspace_read" in host_tool_names
    assert "workspace_write" in host_tool_names
