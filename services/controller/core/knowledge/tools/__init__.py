"""MCP tool registration for the ARES Knowledge Base.

Each tool module registers its tools through a function call.
The host_capability_mcp_server.py imports register_all_kb_tools and calls it once.
"""

from __future__ import annotations

from typing import Any, Callable

# Capabilities declared by this module — auto-granted by configure-system-fabric.py
KB_CAPABILITIES = [
    "kb.query",
    "kb.ingest",
    "kb.status",
    "kb.remove",
    "kb.graph.query",
    "kb.graph.status",
    "kb.graph.build",
    "memory.query",
    "memory.context",
]


def register_all_kb_tools(
    mcp: Any,
    require_fn: Callable[[str], dict],
    audit_fn: Callable[..., None],
    resolve_fn: Callable[..., Any],
) -> None:
    """Register all knowledge base MCP tools.

    Called once from host_capability_mcp_server.py:
        from core.knowledge.tools import register_all_kb_tools
        register_all_kb_tools(mcp, _require, _audit, _resolve)
    """
    from .vector_tools import register_vector_tools
    from .graph_tools import register_graph_tools
    from .memory_tools import register_memory_tools

    register_vector_tools(mcp, require_fn, audit_fn, resolve_fn)
    register_graph_tools(mcp, require_fn, audit_fn, resolve_fn)
    register_memory_tools(mcp, require_fn, audit_fn, resolve_fn)