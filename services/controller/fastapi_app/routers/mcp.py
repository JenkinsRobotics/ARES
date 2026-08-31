"""MCP server configuration endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from ..errors import CoreApiError
from ..request_context import (
    RequestIdentity,
    profile_scope,
    require_identity,
    require_mutation_identity,
)
from ..schemas import McpServerToggle, McpServerUpdate

router = APIRouter(tags=["mcp"])

def _call(operation, identity: RequestIdentity, *args):
    from api.mcp_config import McpConfigError

    try:
        with profile_scope(identity.profile):
            return operation(*args)
    except McpConfigError as exc:
        raise CoreApiError(exc.status_code, str(exc)) from exc


@router.get("/api/mcp/servers")
def servers(identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.runtime_mcp import list_runtime_servers, selected_runtime_owns_mcp
    if selected_runtime_owns_mcp():
        return _runtime_call(list_runtime_servers)
    from api.mcp_config import list_servers

    return _call(list_servers, identity)


@router.get("/api/mcp/catalog")
def catalog(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.mcp_catalog import get_mcp_catalog

    return get_mcp_catalog()



@router.put("/api/mcp/servers/{name}")
def update(
    name: str,
    payload: McpServerUpdate,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.runtime_mcp import configure_runtime_server, selected_runtime_owns_mcp
    if selected_runtime_owns_mcp():
        return _runtime_call(configure_runtime_server, name, payload.model_dump(exclude_none=True))
    from api.mcp_config import update_server

    return _call(update_server, identity, name, payload.model_dump(exclude_none=True))


@router.patch("/api/mcp/servers/{name}")
def toggle(
    name: str,
    payload: McpServerToggle,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.runtime_mcp import selected_runtime_owns_mcp, toggle_runtime_server
    if selected_runtime_owns_mcp():
        return _runtime_call(toggle_runtime_server, name, payload.enabled)
    from api.mcp_config import toggle_server

    return _call(toggle_server, identity, name, payload.enabled)


@router.delete("/api/mcp/servers/{name}")
def delete(name: str, identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.runtime_mcp import remove_runtime_server, selected_runtime_owns_mcp
    if selected_runtime_owns_mcp():
        return _runtime_call(remove_runtime_server, name)
    from api.mcp_config import delete_server

    return _call(delete_server, identity, name)


def _runtime_call(operation, *args):
    from api.runtime_mcp import RuntimeMCPError
    try:
        return operation(*args)
    except RuntimeMCPError as exc:
        raise CoreApiError(exc.status_code, str(exc)) from exc


@router.post("/api/mcp/reload")
def reload_tools(_identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.runtime_mcp import reload_runtime_tools, selected_runtime_owns_mcp
    if not selected_runtime_owns_mcp():
        raise CoreApiError(409, "MCP reload is owned by the selected runtime")
    return _runtime_call(reload_runtime_tools)


__all__ = ["router"]
