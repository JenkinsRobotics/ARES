"""Selected-runtime routing for MCP configuration and tool inventory."""

from __future__ import annotations

from typing import Any

from api.backend_catalog import JAEGER_BACKEND_ID


class RuntimeMCPError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def selected_runtime_owns_mcp() -> bool:
    from api.backend_selector import get_active_backend
    from api.config import get_config
    return get_active_backend(get_config()) == JAEGER_BACKEND_ID


def _require_support() -> None:
    from api.ares_capabilities import capability_contract_for_backend
    negotiated = capability_contract_for_backend(JAEGER_BACKEND_ID)
    feature = ((negotiated.get("runtime_contract") or {}).get("features") or {}).get("mcp_server_config") or {}
    if negotiated.get("negotiated") is not True or feature.get("available") is not True:
        raise RuntimeMCPError(str(negotiated.get("error") or
                                  "the selected Jaeger runtime does not advertise MCP support"), 503)


def _query(what: str) -> dict[str, Any]:
    _require_support()
    try:
        from api.providers.jaeger.gateway_streaming import query_local_companion
        value = query_local_companion(what, {})
    except RuntimeMCPError:
        raise
    except Exception as exc:
        raise RuntimeMCPError(f"Jaeger MCP query failed: {exc}", 502) from exc
    if not isinstance(value, dict):
        raise RuntimeMCPError("Jaeger returned an invalid MCP response", 502)
    return value


def _command(name: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_support()
    try:
        from api.providers.jaeger.gateway_streaming import command_local_companion
        value = command_local_companion(name, args)
    except RuntimeMCPError:
        raise
    except Exception as exc:
        raise RuntimeMCPError(f"Jaeger MCP command failed: {exc}", 502) from exc
    return value if isinstance(value, dict) else {"ok": True}


def list_runtime_servers() -> dict[str, Any]:
    return _query("list_mcp_servers")


def list_runtime_tools() -> dict[str, Any]:
    return _query("list_tools")


def configure_runtime_server(name: str, config: dict[str, Any]) -> dict[str, Any]:
    return _command("configure_mcp_server", {"name": name, "config": config})


def toggle_runtime_server(name: str, enabled: bool) -> dict[str, Any]:
    return _command("enable_mcp_server" if enabled else "disable_mcp_server", {"name": name})


def remove_runtime_server(name: str) -> dict[str, Any]:
    return _command("remove_mcp_server", {"name": name})


def reload_runtime_tools() -> dict[str, Any]:
    return _command("reload_tools", {})
