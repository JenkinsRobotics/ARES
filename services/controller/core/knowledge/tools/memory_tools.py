"""Honcho memory MCP tools — memory_query, memory_context, memory_status, memory_add."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def register_memory_tools(
    mcp: Any,
    require_fn: Callable[[str], dict],
    audit_fn: Callable[..., None],
    resolve_fn: Callable[..., Any],
) -> None:

    @mcp.tool()
    def memory_query(
        query: str,
        peer_id: str = "",
        session_id: str = "",
    ) -> dict:
        """Query Honcho's conversational memory for insights about peers.

        Honcho reasons about conversations to build profiles of users and agents.
        Returns representations, conclusions, and context.

        Args:
            query: Natural language question (e.g. "What have you learned about Matthew's working style?")
            peer_id: Peer to query about (e.g. "matthew", "hermes")
            session_id: Optional session to scope the query

        Returns:
            Dict with representation, card, context, and conclusions.
        """
        require_fn("memory.query")
        from ..config import KBConfig
        from ..memory.honcho_client import HonchoClient

        config = KBConfig.from_env()
        client = HonchoClient.from_config(config)

        if not client.health():
            audit_fn("memory.query", outcome="denied", reason="honcho not running")
            return {"error": "Honcho server is not running", "api_url": config.honcho_api_url}

        result: dict = {"query": query}

        if peer_id:
            # Get representation (Honcho's reasoned profile) - scoped to the query
            rep = client.get_peer_representation(peer_id, search_query=query)
            result["representation"] = rep

            # Get peer card (key facts)
            card = client.get_peer_card(peer_id)
            result["card"] = card

            # Get peer context
            ctx = client.get_peer_context(peer_id)
            result["context"] = ctx

            # Query conclusions
            conclusions = client.query_conclusions(query)
            result["conclusions"] = conclusions
        elif session_id:
            # Get session context
            ctx = client.get_session_context(session_id)
            result["session_context"] = ctx

            # Search within session
            search = client.search(query, session_id=session_id)
            result["search_results"] = search
        else:
            # Global search
            search = client.search(query)
            result["search_results"] = search

        audit_fn("memory.query", outcome="allowed", query=query[:200])
        return result

    @mcp.tool()
    def memory_context(
        session_id: str = "",
        peer_id: str = "",
    ) -> dict:
        """Get context injection for a session or peer from Honcho.

        Returns session summary, user representation, and peer card
        that can be injected into an agent's system prompt.

        Args:
            session_id: Session to get context for
            peer_id: Peer to get representation and card for

        Returns:
            Dict with summary, representation, and/or card.
        """
        require_fn("memory.context")
        from ..config import KBConfig
        from ..memory.honcho_client import HonchoClient

        config = KBConfig.from_env()
        client = HonchoClient.from_config(config)

        if not client.health():
            return {"error": "Honcho server is not running", "api_url": config.honcho_api_url}

        result: dict = {}

        if peer_id:
            result["representation"] = client.get_peer_representation(peer_id)
            result["card"] = client.get_peer_card(peer_id)
            result["context"] = client.get_peer_context(peer_id)

        if session_id:
            result["session_context"] = client.get_session_context(session_id)
            result["session_summaries"] = client.get_session_summaries(session_id)

        audit_fn("memory.context", outcome="allowed")
        return result

    @mcp.tool()
    def memory_status() -> dict:
        """Check if Honcho memory server is running and healthy."""
        require_fn("memory.query")
        from ..config import KBConfig
        from ..memory.honcho_setup import check_honcho

        config = KBConfig.from_env()
        status = check_honcho(config)
        audit_fn("memory.status", outcome="allowed")
        return status

    @mcp.tool()
    def memory_add(
        session_id: str,
        peer_id: str,
        content: str,
    ) -> dict:
        """Add a message to a Honcho session for processing.

        The deriver will reason about this message in the background
        to update peer representations and conclusions.

        Args:
            session_id: Session to add the message to
            peer_id: Peer who sent the message (e.g. "matthew", "hermes")
            content: The message content

        Returns:
            Dict with ok status.
        """
        require_fn("memory.context")
        from ..config import KBConfig
        from ..memory.honcho_client import HonchoClient

        config = KBConfig.from_env()
        client = HonchoClient.from_config(config)

        if not client.health():
            return {"error": "Honcho server is not running", "api_url": config.honcho_api_url}

        result = client.add_message(session_id, peer_id, content)
        audit_fn("memory.add", outcome="allowed", session=session_id[:100], peer=peer_id)
        return result