"""Honcho conversational memory bridge.

Wraps the Honcho v3 API for ARES MCP exposure.
Connects to a local or remote Honcho server.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

from ..config import KBConfig

logger = logging.getLogger(__name__)


class HonchoClient:
    """Thin HTTP client for the Honcho v3 API."""

    def __init__(self, base_url: str, api_key: str = "", workspace: str = "ares") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.workspace = workspace
        self._headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    @classmethod
    def from_config(cls, config: KBConfig) -> "HonchoClient":
        api_key = os.environ.get("HONCHO_API_KEY", "")
        return cls(
            base_url=config.honcho_api_url,
            api_key=api_key,
            workspace=os.environ.get("HONCHO_WORKSPACE", "ares"),
        )

    def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("Honcho API call failed: %s %s -> %s", method, path, exc)
            return {"error": str(exc)}

    def health(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/health", headers=self._headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("status") == "ok"
        except Exception:
            return False

    def _ws(self) -> str:
        return f"/v3/workspaces/{self.workspace}"

    # --- Peers ---

    def create_peer(self, peer_id: str, metadata: dict | None = None) -> dict:
        return self._request("POST", f"{self._ws()}/peers", {
            "id": peer_id,
            "metadata": metadata or {},
        })

    def get_peer(self, peer_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/peers/{peer_id}")

    def get_peer_representation(self, peer_id: str, search_query: str = "") -> dict:
        body = {}
        if search_query:
            body["search_query"] = search_query
        return self._request("POST", f"{self._ws()}/peers/{peer_id}/representation", body)

    def get_peer_card(self, peer_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/peers/{peer_id}/card")

    def get_peer_context(self, peer_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/peers/{peer_id}/context")

    def peer_chat(self, peer_id: str, message: str) -> dict:
        return self._request("POST", f"{self._ws()}/peers/{peer_id}/chat", {
            "message": message,
        })

    # --- Sessions ---

    def create_session(self, session_id: str, peers: dict | None = None) -> dict:
        return self._request("POST", f"{self._ws()}/sessions", {
            "id": session_id,
            "peers": peers or {},
        })

    def list_sessions(self) -> dict:
        return self._request("POST", f"{self._ws()}/sessions/list", {})

    def get_session(self, session_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/sessions/{session_id}")

    def get_session_context(self, session_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/sessions/{session_id}/context")

    def get_session_summaries(self, session_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/sessions/{session_id}/summaries")

    # --- Messages ---

    def add_message(self, session_id: str, peer_id: str, content: str) -> dict:
        return self._request("POST", f"{self._ws()}/sessions/{session_id}/messages", {
            "messages": [{"peer_id": peer_id, "content": content}],
        })

    def list_messages(self, session_id: str) -> dict:
        return self._request("POST", f"{self._ws()}/sessions/{session_id}/messages/list", {})

    # --- Search ---

    def search(self, query: str, session_id: str = "") -> dict:
        if session_id:
            return self._request("POST", f"{self._ws()}/sessions/{session_id}/search", {"query": query})
        return self._request("POST", f"{self._ws()}/search", {"query": query})

    # --- Conclusions ---

    def get_conclusions(self, peer_id: str = "") -> dict:
        return self._request("POST", f"{self._ws()}/conclusions/list", {"peer_id": peer_id} if peer_id else {})

    def query_conclusions(self, query: str) -> dict:
        return self._request("POST", f"{self._ws()}/conclusions/query", {"query": query})