"""Expose ARES controller tools to Jaeger through Jaeger's MCP contract.

ARES owns the server executable. Jaeger owns its MCP configuration and runtime;
this module never discovers or writes Jaeger files.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

SERVER_NAME = "ares-controller"


class AresToolsMCPError(RuntimeError):
    pass


def _server_script() -> Path:
    return Path(__file__).resolve().parents[1] / "mcp_server.py"


def _server_config() -> dict[str, Any]:
    script = _server_script()
    if not script.is_file():
        raise AresToolsMCPError(f"ARES MCP server entry point is missing: {script}")
    python = Path(sys.executable).resolve()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise AresToolsMCPError(f"ARES Python executable is unavailable: {python}")
    from api.config import ARES_HOME, PORT, STATE_DIR
    return {
        "command": str(python), "args": [str(script)], "enabled": True,
        "env": {
            "ARES_HOME": str(ARES_HOME),
            "ARES_WEBUI_STATE_DIR": str(STATE_DIR),
            "ARES_WEBUI_PORT": str(PORT),
        },
    }


def _query(what: str) -> dict[str, Any]:
    try:
        from api.providers.jaeger.gateway_streaming import query_local_companion
        result = query_local_companion(what, {})
    except Exception as exc:
        raise AresToolsMCPError(f"Jaeger MCP query failed: {exc}") from exc
    if not isinstance(result, dict):
        raise AresToolsMCPError("Jaeger returned an invalid MCP response")
    return result


def _command(command: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        from api.providers.jaeger.gateway_streaming import command_local_companion
        result = command_local_companion(command, args)
    except Exception as exc:
        raise AresToolsMCPError(f"Jaeger MCP command failed: {exc}") from exc
    return result if isinstance(result, dict) else {"ok": True}


def ares_tools_status() -> dict[str, Any]:
    available = _server_script().is_file() and Path(sys.executable).is_file()
    if not available:
        return {"available": False, "enabled": False, "active": False}
    payload = _query("list_mcp_servers")
    row = next((item for item in payload.get("servers", [])
                if isinstance(item, dict) and item.get("name") == SERVER_NAME), None)
    return {"available": True, "enabled": bool(row and row.get("enabled")),
            "active": bool(row and row.get("active")), "server": row}


def set_ares_tools_enabled(enabled: bool) -> dict[str, Any]:
    if enabled:
        configured = _command("configure_mcp_server", {
            "name": SERVER_NAME, "config": _server_config(),
        })
    else:
        status = ares_tools_status()
        if not status.get("server"):
            return {"ok": True, "enabled": False, "active": False}
        configured = _command("disable_mcp_server", {"name": SERVER_NAME})
    reloaded = _command("reload_tools", {})
    status = ares_tools_status()
    return {"ok": True, **status, "configuration": configured, "reload": reloaded}
