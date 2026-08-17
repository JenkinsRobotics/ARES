"""ARES Runtime Context — builds live operating state every turn.

ARES projects the active runtime's identity. This module produces a compact context
packet that gets injected into the agent's system prompt every turn,
regardless of which external backend is active.

The context tells the agent:
  - Who it is (projected backend identity)
  - Which backend is running
  - What capabilities are available
  - What open promises/tasks exist
  - Whether JROS embodiment is connected

This is backend-agnostic and never treats ARES itself as an inference runtime.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

# Lazy import — avoids circular dependency at module level.
# backend_selector.is_jros_available() is the canonical probe.
_IS_JROS_AVAILABLE_FUNC: Optional[Any] = None


def _get_jros_available_func():
    """Lazy-load the JROS availability check from backend_selector."""
    global _IS_JROS_AVAILABLE_FUNC
    if _IS_JROS_AVAILABLE_FUNC is not None:
        return _IS_JROS_AVAILABLE_FUNC
    try:
        from api.backend_selector import is_jros_available
        _IS_JROS_AVAILABLE_FUNC = is_jros_available
    except ImportError:
        logging.getLogger(__name__).debug(
            "backend_selector not available — JROS assumed down"
        )
        _IS_JROS_AVAILABLE_FUNC = lambda: False
    return _IS_JROS_AVAILABLE_FUNC


def is_jros_available() -> bool:
    """Check if JROS daemon is reachable. Delegates to backend_selector."""
    func = _get_jros_available_func()
    try:
        return bool(func())
    except Exception:
        return False


# ── Build Runtime Context ─────────────────────────────────────────

def build_runtime_context(
    backend: str = "",
    *,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Build the ARES runtime context packet.

    This is injected into the agent's system prompt every turn so
    the agent knows the projected identity, backend, and available capabilities.

    Args:
        backend: Canonical external runtime adapter ID.
        session_id: Optional session identifier.

    Returns:
        Dict with ARES operating state.
    """
    try:
        from api.ares_self_persistence import should_inject_self_persistence
    except ImportError:
        # Fallback: self-persistence is opt-in
        def should_inject_self_persistence(config):
            return True

    jros_up = is_jros_available()

    from api.backend_selector import normalize_backend

    effective_backend = normalize_backend(backend)

    # Capability map — what each backend provides
    capabilities = {
        "ares_resources": {
            "available": True,
            "provides": [
                "tools", "skills", "cron", "memory",
                "delegation", "terminal", "web_search",
                "browser", "file_ops", "sessions", "routing",
                "permissions", "continuity",
            ],
        },
        "jros": {
            "available": jros_up,
            "provides": [
                "embodiment", "speech", "hearing", "vision",
                "motor_control", "animation", "skill_tree",
                "timeline",
            ] if jros_up else [],
        },
        "active_runtime": {
            "id": effective_backend,
            "available": bool(effective_backend),
            "provides": ["inference", "identity_projection"] if effective_backend else [],
        },
    }

    # Tasks use the same canonical store as the Kanban UI and dispatcher.
    open_tasks: list[dict[str, str]] = []
    try:
        from api import kanban_store

        kanban_store.init_db()
        with kanban_store.connect_closing() as conn:
            tasks = kanban_store.list_tasks(conn)
        open_tasks = [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "priority": str(task.priority),
            }
            for task in tasks
            if task.status not in {"done", "archived"}
        ][:10]
    except Exception:
        pass  # DB not ready — empty tasks is fine

    # Promise persistence remains empty until it has a canonical owner and
    # mutation contract.
    open_promises: list[dict[str, str]] = []

    device_summary: dict[str, Any] = {}
    try:
        from api.ares_devices import device_status
        from api.config import get_config

        status = device_status(get_config())
        device = status.get("device") if isinstance(status, dict) else {}
        device_summary = {
            "ai_id": status.get("ai_id", ""),
            "role": status.get("role", ""),
            "is_primary": bool(status.get("is_primary")),
            "device_id": device.get("device_id", "") if isinstance(device, dict) else "",
            "device_name": device.get("device_name", "") if isinstance(device, dict) else "",
            "primary": status.get("primary", {}),
        }
    except Exception:
        device_summary = {}

    context: dict[str, Any] = {
        "identity_projection": _identity_projection_for_backend(effective_backend),
        "active_backend": effective_backend,
        "session_id": session_id or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "capabilities": capabilities,
        "open_tasks": open_tasks,
        "open_promises": open_promises,
        "self_persistence_enabled": should_inject_self_persistence({}),
        "embodiment": {
            "body": "desktop" if not jros_up else "droid",
            "jros_connected": jros_up,
        },
        "device": device_summary,
    }

    return context


# ── Render for Prompt Injection ───────────────────────────────────

def render_context_prompt(context: dict[str, Any]) -> str:
    """Render the runtime context into a compact system prompt block.

    This is injected above persona/backend-specific prompts so ARES
    operating state is visible without claiming canonical persona ownership.

    Designed to be under 500 chars to minimize context window impact.
    """
    backend = context.get("active_backend", "")
    identity = context.get("identity_projection", {})
    if not isinstance(identity, dict):
        identity = {}
    identity_name = str(identity.get("name") or "No runtime selected")
    jros_up = context.get("capabilities", {}).get("jros", {}).get("available", False)
    lines = [
        f"Projected identity: {identity_name}. Backend: {backend}.",
    ]

    if jros_up:
        lines.append("JROS embodiment connected: speech, hearing, vision, motor control available.")
    else:
        lines.append("No JROS embodiment — desktop mode.")

    device = context.get("device") or {}
    if isinstance(device, dict) and device.get("role"):
        role = "primary AI body" if device.get("is_primary") else "joined ARES device"
        lines.append(f"ARES device: {device.get('device_id') or 'unknown'} ({role}).")

    # Compact task count
    tasks = context.get("open_tasks", [])
    if tasks:
        lines.append(f"Open tasks: {len(tasks)}.")

    promises = context.get("open_promises", [])
    if promises:
        lines.append(f"Unresolved promises: {len(promises)}.")

    return "\n".join(lines)


def _identity_projection_for_backend(backend: str) -> dict[str, Any]:
    """Return the active backend identity projection without making ARES canonical."""

    from api.backend_selector import normalize_backend

    normalized = normalize_backend(backend)
    try:
        from api.backends.router import get_router

        selected = get_router().backends.get(normalized)
        if selected is not None:
            projection = selected.identity_projection()
            if isinstance(projection, dict):
                return projection
    except Exception:
        pass

    return {
        "name": normalized.replace("_", " ").title() if normalized else "No runtime selected",
        "description": "External runtime identity projection unavailable",
        "avatar_state": "idle",
    }
