"""Dynamic inventory and catalog of all ARES MCP servers, tools, and capabilities."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def _extract_schema(tool_obj: Any) -> dict[str, Any]:
    raw = getattr(tool_obj, "input_schema", getattr(tool_obj, "parameters", None))
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        return raw.model_dump()
    return {}


def _get_system_tools() -> list[dict[str, Any]]:
    try:
        import system_mcp_server
        tools = system_mcp_server.mcp._tool_manager._tools.values()
        return [
            {
                "name": t.name,
                "description": (t.description or "").strip(),
                "parameters": _extract_schema(t),
                "capability": None,
            }
            for t in tools
        ]
    except Exception:
        return []


def _get_host_tools() -> list[dict[str, Any]]:
    try:
        import host_capability_mcp_server
        tools = host_capability_mcp_server.mcp._tool_manager._tools.values()
        return [
            {
                "name": t.name,
                "description": (t.description or "").strip(),
                "parameters": _extract_schema(t),
                "capability": getattr(t, "capability", None) or f"host.{t.name}",
            }
            for t in tools
        ]
    except Exception:
        return []


def _get_webui_tools() -> list[dict[str, Any]]:
    try:
        import mcp_server
        return [
            {
                "name": t.name,
                "description": (t.description or "").strip(),
                "parameters": _extract_schema(t),
                "capability": None,
            }
            for t in mcp_server.TOOLS
        ]
    except Exception:
        return []


def _get_native_tools() -> list[dict[str, Any]]:
    try:
        from fastapi_app.adapters.mcp import McpToolAdapter
        tools = McpToolAdapter._native_tools()
        if tools:
            return tools
    except Exception:
        pass

    # Standard macOS helper capabilities manifest
    return [
        {"name": "calendar_query", "description": "Query EventKit calendar entries."},
        {"name": "calendar_create", "description": "Create calendar events in macOS Calendar."},
        {"name": "contacts_search", "description": "Search macOS AddressBook contacts."},
        {"name": "notes_query", "description": "Query Apple Notes database."},
        {"name": "notes_create", "description": "Create new notes in Apple Notes."},
        {"name": "screencapture", "description": "ScreenCaptureKit window and display capture."},
        {"name": "spotlight_search", "description": "Search macOS files and metadata via Spotlight."},
        {"name": "todo_operations", "description": "macOS Reminders integration."},
        {"name": "user_collaboration", "description": "macOS Notification and collaboration."},
        {"name": "weather", "description": "macOS WeatherKit live weather information."},
    ]


def _get_gateway_info() -> dict[str, Any]:
    gateway_file = Path(os.environ.get("ARES_HOME") or Path.home() / ".ares") / "gateway" / "config.yaml"
    targets: list[dict[str, Any]] = []
    port = 8811

    if gateway_file.is_file():
        try:
            cfg = yaml.safe_load(gateway_file.read_text(encoding="utf-8")) or {}
            mcp_cfg = cfg.get("mcp", {})
            port = mcp_cfg.get("port", 8811)
            raw_targets = mcp_cfg.get("targets", [])
            for target in raw_targets:
                name = target.get("name")
                if name:
                    targets.append({
                        "target": name,
                        "server_id": f"ares-{name}" if not name.startswith("ares-") else name,
                        "prefix": f"{name}_*",
                    })
        except Exception:
            pass

    if not targets:
        targets = [
            {"target": "system", "server_id": "ares-system", "prefix": "system_*"},
            {"target": "host-hermes", "server_id": "ares-host", "prefix": "host-hermes_*"},
        ]

    return {
        "name": "agentgateway",
        "port": port,
        "endpoint": f"http://127.0.0.1:{port}/mcp",
        "auth_mode": "strict-bearer",
        "client_token_path": str(Path.home() / ".ares" / "gateway" / "client.token"),
        "federated_targets": targets,
    }


def get_mcp_catalog() -> dict[str, Any]:
    """Return the authoritative, dynamically introspected catalog of all MCP servers and tools."""
    servers: list[dict[str, Any]] = []

    # 1. ares-system (introspected from system_mcp_server.mcp)
    system_tools = _get_system_tools()
    servers.append({
        "id": "ares-system",
        "name": "ARES System Control Plane",
        "transport": "stdio",
        "entrypoint": "services/controller/system_mcp_server.py",
        "gateway_target": "system",
        "gateway_url": "http://127.0.0.1:8811/mcp",
        "description": "Governed automation control plane for goals, runs, status, and approvals.",
        "auth": "Strict bearer token (~/.ares/gateway/client.token)",
        "tool_count": len(system_tools),
        "tools": system_tools,
    })

    # 2. ares-host (introspected from host_capability_mcp_server.mcp)
    host_tools = _get_host_tools()
    servers.append({
        "id": "ares-host",
        "name": "ARES Host Capabilities & Perception",
        "transport": "stdio",
        "entrypoint": "services/controller/host_capability_mcp_server.py",
        "gateway_target": "host-hermes",
        "gateway_url": "http://127.0.0.1:8811/mcp",
        "description": "Capability-gated host integration plane (workspace, camera, notes, reminders, git).",
        "auth": "Identity token scoped per agent",
        "tool_count": len(host_tools),
        "tools": host_tools,
    })

    # 3. ares-webui (introspected from mcp_server.TOOLS)
    webui_tools = _get_webui_tools()
    servers.append({
        "id": "ares-webui",
        "name": "ARES WebUI Workspace & Session Management",
        "transport": "stdio",
        "entrypoint": "services/controller/mcp_server.py",
        "gateway_target": None,
        "gateway_url": None,
        "description": "Project, session, and context management tools for interactive WebUI sessions.",
        "auth": "Session password / local process boundary",
        "tool_count": len(webui_tools),
        "tools": webui_tools,
    })

    # 4. ares-native-mcp
    native_tools = _get_native_tools()
    servers.append({
        "id": "ares-native-mcp",
        "name": "ARES Native macOS Helper",
        "transport": "stdio",
        "entrypoint": "apps/macos/Sources/ARESNativeMCP/main.swift",
        "gateway_target": None,
        "gateway_url": None,
        "description": "Native macOS Swift framework tool plane for system integrations.",
        "auth": "macOS TCC permissions (Calendar, Contacts, Reminders, Screen Recording)",
        "tool_count": len(native_tools),
        "tools": native_tools,
    })

    # 5. jaeger-mcp-proxy (mirrors host tools over loopback companion)
    servers.append({
        "id": "jaeger-mcp-proxy",
        "name": "Jaeger MCP Proxy",
        "transport": "stdio-bridge",
        "entrypoint": "services/controller/jaeger_mcp_proxy.py",
        "gateway_target": None,
        "gateway_url": None,
        "description": "Direct bridge to Jaeger companion MCP tools.",
        "auth": "Loopback IPC",
        "tool_count": len(host_tools),
        "tools": host_tools,
    })

    total_tools = sum(s["tool_count"] for s in servers)

    return {
        "ok": True,
        "version": 1,
        "total_servers": len(servers),
        "total_tools": total_tools,
        "servers": servers,
        "gateway": _get_gateway_info(),
    }
