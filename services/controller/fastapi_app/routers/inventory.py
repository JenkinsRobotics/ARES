"""Live repository/runtime inventory for humans, agents, and the WebUI."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.routing import APIRoute

from ..request_context import RequestIdentity, profile_scope, require_identity


router = APIRouter(prefix="/api/inventory", tags=["inventory"])


def _route_inventory() -> dict[str, Any]:
    from fastapi_app.routers import CORE_ROUTER_REGISTRY

    rows = []
    for registration in CORE_ROUTER_REGISTRY:
        for route in registration.router.routes:
            if not isinstance(route, APIRoute):
                continue
            methods = sorted((route.methods or set()) - {"HEAD", "OPTIONS"})
            if not methods:
                continue
            rows.append(
                {
                    "router": registration.name,
                    "path": route.path,
                    "methods": methods,
                    "name": route.name,
                    "tags": list(route.tags or []),
                }
            )
    pairs = Counter((method, row["path"]) for row in rows for method in row["methods"])
    duplicates = [
        {"method": method, "path": path, "registrations": count}
        for (method, path), count in sorted(pairs.items())
        if count > 1
    ]
    return {"count": len(rows), "items": rows, "duplicates": duplicates}


def _tool_inventory(runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    from api.ares_tools import ARES_TOOL_DEFS
    from mcp_server import HANDLERS as MANAGEMENT_HANDLERS, TOOLS as MANAGEMENT_TOOLS

    groups = {
        "ares": [
            {
                "name": item["name"],
                "description": item["description"],
                "available": callable(item.get("fn")),
                "status": "registered" if callable(item.get("fn")) else "unavailable",
            }
            for item in ARES_TOOL_DEFS
        ],
        "management_mcp": [
            {
                "name": item.name,
                "description": item.description,
                "available": callable(MANAGEMENT_HANDLERS.get(item.name)),
                "status": "registered" if callable(MANAGEMENT_HANDLERS.get(item.name)) else "unavailable",
            }
            for item in MANAGEMENT_TOOLS
        ],
    }
    if runtime is not None:
        groups["runtime"] = runtime.get("items", [])
    unique_names = {
        str(item.get("name") or "")
        for items in groups.values()
        for item in items
        if str(item.get("name") or "")
    }
    return {
        "count": len(unique_names),
        "groups": groups,
        "runtime_error": (runtime or {}).get("error"),
    }


def _runtime_tool_inventory(request: Request, profile: str) -> dict[str, Any]:
    from api.runtime_mcp import list_runtime_tools, selected_runtime_owns_mcp

    try:
        if selected_runtime_owns_mcp():
            payload = list_runtime_tools()
        else:
            payload = request.app.state.adapter_registry.tool_adapter("mcp").list_tools(
                profile=profile
            )
        raw = payload.get("tools", []) if isinstance(payload, dict) else []
        items = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "name": str(item.get("name") or ""),
                    "description": str(item.get("description") or ""),
                    "source": str(item.get("source") or item.get("server") or "runtime"),
                    "available": True,
                    "status": "advertised",
                }
            )
        return {"items": items, "error": None}
    except Exception as exc:  # runtime inventory is optional and fails closed
        return {"items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.get("")
def inventory(
    request: Request,
    identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Return calculated inventory; no counts or availability are persisted."""
    from api.ares_capabilities import capability_contract_for_backend
    from api.backend_selector import get_active_backend
    from api.config import get_config
    from api.runtime_skills import list_runtime_skills, selected_runtime_owns_skills
    from api.skills_store import list_skills
    from fastapi_app.routers import CORE_ROUTER_REGISTRY

    with profile_scope(identity.profile):
        backend = get_active_backend(get_config())
        capability_contract = capability_contract_for_backend(backend)
        try:
            skill_result = (
                list_runtime_skills()
                if selected_runtime_owns_skills()
                else list_skills()
            )
            skills = list(skill_result.get("skills") or [])
            skill_error = None
        except Exception as exc:  # optional runtime inventory fails closed
            skills = []
            skill_error = f"{type(exc).__name__}: {exc}"

    routers = [
        {
            "name": entry.name,
            "legacy": entry.legacy,
            "status": "registered",
            "routes": sum(isinstance(route, APIRoute) for route in entry.router.routes),
        }
        for entry in CORE_ROUTER_REGISTRY
    ]
    routes = _route_inventory()
    tools = _tool_inventory(_runtime_tool_inventory(request, identity.profile))
    return {
        "schema_version": 1,
        "generated": True,
        "backend": backend,
        "summary": {
            "routers": len(routers),
            "routes": routes["count"],
            "tools": tools["count"],
            "skills": len(skills),
            "capabilities": len(capability_contract["capabilities"]),
            "available_capabilities": sum(capability_contract["capabilities"].values()),
        },
        "routers": routers,
        "routes": routes,
        "tools": tools,
        "skills": {"count": len(skills), "items": skills, "error": skill_error},
        "capabilities": capability_contract,
    }


__all__ = ["router"]
