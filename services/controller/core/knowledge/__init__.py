"""ARES Knowledge Base — Hybrid RAG system.

Three retrieval layers exposed as MCP tools through host_capability_mcp_server.py:

1. Vector RAG (LanceDB) — semantic + keyword hybrid search over documents
2. GraphRAG — entity/relationship extraction for multi-hop reasoning
3. Honcho — conversational memory with dialectic reasoning

All data lives at /Volumes/Jenkins_Robotics/Alexandria/ on the UNAS-Pro.
All code lives here, isolated from the existing core/memory/ module.
"""

from .tools import KB_CAPABILITIES, register_all_kb_tools

__all__ = ["KB_CAPABILITIES", "register_all_kb_tools"]