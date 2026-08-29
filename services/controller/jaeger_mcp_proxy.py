"""MCP facade for the already-running native Jaeger bridge.

This process never imports or starts JaegerAI. It translates MCP calls into
Jaeger's versioned loopback runner API, keeping the native runtime, sessions,
tools, macOS permissions, and model configuration owned by Jaeger.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # MCP SDK 2.x renamed the server implementation.
    from mcp.server.mcpserver import MCPServer as FastMCP


BASE_URL = os.environ.get("JAEGER_BRIDGE_URL", "http://127.0.0.1:8791").rstrip("/")
mcp = FastMCP("jaeger-native")


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
        raise RuntimeError(f"Jaeger rejected {method} {path}: HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Native Jaeger bridge is unavailable at {BASE_URL}: {exc.reason}") from exc
    if len(raw) > 2_000_000:
        raise RuntimeError("Jaeger response exceeded the MCP safety limit")
    return json.loads(raw.decode("utf-8"))


def _run(run_id: str) -> dict[str, Any]:
    return dict(_request("GET", f"/v1/runs/{urllib.parse.quote(run_id, safe='')}"))


@mcp.tool()
def status() -> dict[str, Any]:
    """Return the health, identity, and active model of native JaegerAI."""

    return dict(_request("GET", "/health"))


@mcp.tool()
def message(
    text: str,
    session_id: str = "",
    wait_seconds: int = 0,
    model: str = "",
) -> dict[str, Any]:
    """Send a message directly to native JaegerAI and preserve its session ID."""

    prompt = text.strip()
    if not prompt:
        raise ValueError("text is required")
    sid = session_id.strip() or f"mcp:{uuid.uuid4()}"
    request: dict[str, Any] = {"message": prompt, "session_id": sid}
    if model.strip():
        request["model"] = model.strip()
    started = _request("POST", "/v1/runs", request)
    run = dict(started)
    deadline = time.monotonic() + max(0, min(int(wait_seconds), 120))
    while wait_seconds > 0 and time.monotonic() < deadline:
        run = _run(str(started["run_id"]))
        if run.get("status") not in {"queued", "running", "cancelling"}:
            break
        time.sleep(0.25)
    return {"session_id": sid, "run": run}


@mcp.tool()
def run_status(run_id: str, cursor: str = "") -> dict[str, Any]:
    """Return a native Jaeger run plus evidence events after an optional cursor."""

    encoded = urllib.parse.quote(run_id.strip(), safe="")
    if not encoded:
        raise ValueError("run_id is required")
    suffix = f"?cursor={urllib.parse.quote(cursor, safe='')}" if cursor else ""
    return {
        "run": _run(run_id),
        "events": _request("GET", f"/v1/runs/{encoded}/events{suffix}"),
    }


@mcp.tool()
def cancel(run_id: str) -> dict[str, Any]:
    """Safely cancel one active native Jaeger run."""

    encoded = urllib.parse.quote(run_id.strip(), safe="")
    if not encoded:
        raise ValueError("run_id is required")
    return dict(_request("POST", f"/v1/runs/{encoded}/cancel", {}))


if __name__ == "__main__":
    mcp.run()
