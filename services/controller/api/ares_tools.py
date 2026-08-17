"""ARES Tools — callable tool implementations owned by ARES.

These are the actual functions the agent can call to interact with
ARES's runtime context and canonical task store.

Each tool returns a JSON string (matching both Ares and JROS tool
result conventions). They are backend-agnostic and never write worker stores.
"""

from __future__ import annotations

import json
from pydantic import BaseModel, Field


# ── Tool Argument Models ──────────────────────────────────────────

class GetRuntimeContextArgs(BaseModel):
    """No arguments — returns current ARES operating state."""
    pass


class CreateTaskArgs(BaseModel):
    """Create a new ARES-owned task."""
    title: str = Field(description="Short task title")
    description: str = Field(default="", description="Task description")
    priority: str = Field(default="medium", description="Priority: low, medium, high")


class UpdateTaskArgs(BaseModel):
    """Update an existing ARES task's status."""
    task_id: str = Field(description="The task ID to update")
    status: str = Field(description="New status: open, in_progress, blocked, done")


# ── Tool Implementations ──────────────────────────────────────────

def ares_get_runtime_context(**kwargs) -> str:
    """Get the current ARES runtime context.

    Returns the active backend, capabilities, open tasks,
    and embodiment state as a JSON string.
    """
    try:
        from api.ares_runtime_context import build_runtime_context
    except ImportError:
        # Circular import fallback
        def build_runtime_context(**kw):
            return {"identity": "ARES", "active_backend": "ares"}

    ctx = build_runtime_context()
    return json.dumps(ctx, indent=2, default=str)


def ares_create_task(
    title: str = "",
    description: str = "",
    priority: str = "medium",
    **kwargs,
) -> str:
    """Create a new ARES-owned task in the persistence layer.

    This is a callable ARES tool — the agent can use it to
    capture commitments and follow-ups durably.
    """
    if not title:
        return json.dumps({"status": "error", "error": "title is required"})

    try:
        from api import kanban_store

        priority_value = {"low": 0, "medium": 50, "high": 100}.get(priority.lower())
        if priority_value is None:
            return json.dumps({"status": "error", "error": "priority must be low, medium, or high"})
        kanban_store.init_db()
        with kanban_store.connect_closing() as conn:
            task_id = kanban_store.create_task(
                conn,
                title=title,
                body=description or None,
                priority=priority_value,
                created_by="ares-agent-tool",
            )
            task = kanban_store.get_task(conn, task_id)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})

    return json.dumps({
        "status": "created",
        "id": task_id,
        "title": title,
        "priority": priority,
        "task": task.__dict__ if task is not None else None,
    })


def ares_update_task(
    task_id: str = "",
    status: str = "",
    **kwargs,
) -> str:
    """Update an existing ARES task's status."""
    if not task_id:
        return json.dumps({"status": "error", "error": "task_id is required"})

    try:
        from api import kanban_store

        normalized = {"open": "ready", "in_progress": "running"}.get(status, status)
        kanban_store.init_db()
        with kanban_store.connect_closing() as conn:
            updated = kanban_store.set_task_status(conn, task_id, normalized)
        if not updated:
            return json.dumps({"status": "error", "error": f"task {task_id} not found"})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})

    return json.dumps({
        "status": "updated",
        "id": task_id,
        "new_status": normalized,
    })


# ── Tool Definitions Catalog ──────────────────────────────────────

ARES_TOOL_DEFS = [
    {
        "name": "ares_get_runtime_context",
        "description": (
            "Get the current ARES runtime context: active backend, "
            "capabilities, open tasks, embodiment state. Use this to "
            "understand what ARES can do right now."
        ),
        "fn": ares_get_runtime_context,
        "args_model": GetRuntimeContextArgs,
    },
    {
        "name": "ares_create_task",
        "description": (
            "Create a new ARES-owned task. Use this when you make a "
            "commitment or promise that should persist across sessions."
        ),
        "fn": ares_create_task,
        "args_model": CreateTaskArgs,
    },
    {
        "name": "ares_update_task",
        "description": (
            "Update an ARES task's status (e.g. mark as done, blocked, "
            "in_progress)."
        ),
        "fn": ares_update_task,
        "args_model": UpdateTaskArgs,
    },
]
