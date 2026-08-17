"""Live repository/runtime inventory for humans, agents, and the WebUI."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends
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


def _tool_inventory() -> dict[str, Any]:
    from api.ares_tools import ARES_TOOL_DEFS
    from mcp_server import TOOLS as MANAGEMENT_TOOLS

    groups = {
        "ares": [
            {"name": item["name"], "description": item["description"]}
            for item in ARES_TOOL_DEFS
        ],
        "management_mcp": [
            {"name": item.name, "description": item.description}
            for item in MANAGEMENT_TOOLS
        ],
    }
    return {
        "count": sum(len(items) for items in groups.values()),
        "groups": groups,
    }


@router.get("")
def inventory(
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
        {"name": entry.name, "legacy": entry.legacy}
        for entry in CORE_ROUTER_REGISTRY
    ]
    routes = _route_inventory()
    tools = _tool_inventory()
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
