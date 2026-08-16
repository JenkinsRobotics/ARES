"""MCP server configuration endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from ..errors import CoreApiError
from ..request_context import RequestIdentity, profile_scope, require_identity, require_mutation_identity
from ..schemas import McpServerToggle, McpServerUpdate


router = APIRouter(tags=["mcp"])

_MCP_CATALOG_TEMPLATES = [
    {
        "id": "filesystem",
        "name": "Local Filesystem",
        "description": "Secure file reading, writing, directory navigation, and file search within specified paths.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "~/Desktop", "~/Downloads"],
        "category": "Core",
    },
    {
        "id": "github",
        "name": "GitHub Integration",
        "description": "Repository inspection, pull request automation, issue searching, and branch management.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env_vars": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "category": "Developer Tools",
    },
    {
        "id": "sqlite",
        "name": "SQLite Database",
        "description": "Local SQLite database querying, schema inspection, and data manipulation.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-sqlite", "--db-path", "~/.ares/ares.db"],
        "category": "Database",
    },
    {
        "id": "fetch",
        "name": "Web Content Fetcher",
        "description": "Clean markdown fetching and text extraction from web pages and API endpoints.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "category": "Web",
    },
    {
        "id": "brave-search",
        "name": "Brave Web Search",
        "description": "Privacy-preserving web search and news indexing.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env_vars": ["BRAVE_API_KEY"],
        "category": "Search",
    },
    {
        "id": "linear",
        "name": "Linear Issue Tracker",
        "description": "Manage Linear issues, project boards, and sprints directly from conversations.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "linear-mcp-server"],
        "env_vars": ["LINEAR_API_KEY"],
        "category": "Productivity",
    },
]


def _call(operation, identity: RequestIdentity, *args):
    from api.mcp_config import McpConfigError

    try:
        with profile_scope(identity.profile):
            return operation(*args)
    except McpConfigError as exc:
        raise CoreApiError(exc.status_code, str(exc)) from exc


@router.get("/api/mcp/servers")
def servers(identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.mcp_config import list_servers

    return _call(list_servers, identity)


@router.get("/api/mcp/catalog")
def catalog(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    return {
        "ok": True,
        "catalog": _MCP_CATALOG_TEMPLATES,
        "diagnostics": [],
    }


@router.put("/api/mcp/servers/{name}")
def update(
    name: str,
    payload: McpServerUpdate,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.mcp_config import update_server

    return _call(update_server, identity, name, payload.model_dump(exclude_none=True))


@router.patch("/api/mcp/servers/{name}")
def toggle(
    name: str,
    payload: McpServerToggle,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.mcp_config import toggle_server

    return _call(toggle_server, identity, name, payload.enabled)


@router.delete("/api/mcp/servers/{name}")
def delete(name: str, identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.mcp_config import delete_server

    return _call(delete_server, identity, name)


__all__ = ["router"]

