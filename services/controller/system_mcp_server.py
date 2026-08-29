"""ARES System MCP server.

Agentgateway starts this stdio process and federates it alongside the native
Hermes and Jaeger MCP servers.  Mutations go through ARES' loopback HTTP API,
so this process never opens another automation store or reads agent state.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # MCP SDK 2.x renamed the server implementation.
    from mcp.server.mcpserver import MCPServer as FastMCP


BASE_URL = os.environ.get("ARES_SYSTEM_URL", "http://127.0.0.1:8788").rstrip("/")
mcp = FastMCP("ares-system")


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(2_000_001)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ARES rejected {method} {path}: HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ARES is unavailable at {BASE_URL}: {exc.reason}") from exc
    if len(raw) > 2_000_000:
        raise RuntimeError("ARES response exceeded the MCP safety limit")
    return json.loads(raw.decode("utf-8"))


def _find_run(run_id: str) -> dict[str, Any]:
    rows = _request("GET", "/api/runs")
    run = next((row for row in rows if row.get("id") == run_id), None)
    if run is None:
        raise ValueError(f"Unknown ARES run: {run_id}")
    return run


@mcp.tool()
def system_status() -> dict[str, Any]:
    """Return the safe ARES control-plane status and recent run summary."""

    agents = _request("GET", "/api/agents")
    runs = _request("GET", "/api/runs")
    approvals = _request("GET", "/api/approvals")
    return {
        "paused": bool(agents.get("paused")),
        "agents": len(agents.get("agents") or []),
        "active_runs": [row for row in runs if row.get("status") in {"queued", "running"}],
        "pending_approvals": [row for row in approvals if row.get("status") == "pending"],
    }


@mcp.tool()
def agents_list() -> list[dict[str, Any]]:
    """List independently owned agents registered with ARES."""

    return list(_request("GET", "/api/agents").get("agents") or [])


@mcp.tool()
def system_message(message: str, agent_id: str = "hermes", wait_seconds: int = 0) -> dict[str, Any]:
    """Create a durable goal and delegate it to Hermes or JaegerAI.

    Set ``wait_seconds`` to a small positive number to collect a short result;
    otherwise use ``run_status`` with the returned run ID.
    """

    if agent_id not in {"hermes", "jaeger"}:
        raise ValueError("agent_id must be hermes or jaeger")
    objective = message.strip()
    if not objective:
        raise ValueError("message is required")
    goal = _request("POST", "/api/goals", {"agent_id": agent_id, "objective": objective})
    run = _request(
        "POST",
        f"/api/agents/{agent_id}/wake",
        {
            "goal_id": goal["id"],
            "trigger": "mcp",
            "idempotency_key": f"mcp:{uuid.uuid4()}",
        },
    )
    deadline = time.monotonic() + max(0, min(int(wait_seconds), 120))
    while wait_seconds > 0 and time.monotonic() < deadline:
        run = _find_run(run["id"])
        if run.get("status") not in {"queued", "running"}:
            break
        time.sleep(0.25)
    return {"goal": goal, "run": run}


@mcp.tool()
def run_status(run_id: str) -> dict[str, Any]:
    """Return one ARES run and its immutable evidence events."""

    return {"run": _find_run(run_id), "events": _request("GET", f"/api/runs/{run_id}/events")}


@mcp.tool()
def run_cancel(run_id: str) -> dict[str, Any]:
    """Safely request cancellation of an active ARES run."""

    return _request("POST", f"/api/runs/{run_id}/cancel", {})


@mcp.tool()
def approval_respond(approval_id: str, decision: str) -> dict[str, Any]:
    """Approve or deny one pending consequential action."""

    if decision not in {"approved", "denied"}:
        raise ValueError("decision must be approved or denied")
    return _request("POST", "/api/approvals", {"id": approval_id, "decision": decision})


if __name__ == "__main__":
    mcp.run()
