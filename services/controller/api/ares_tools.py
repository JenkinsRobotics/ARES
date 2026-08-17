"""ARES Tools — callable tool implementations owned by ARES.

These are the actual functions the agent can call to interact with
ARES's runtime context and canonical task store.

Each tool returns a JSON string (matching both Ares and JROS tool
result conventions). They are backend-agnostic and never write worker stores.
"""

from __future__ import annotations

import json
from typing import Any
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


class WorkspacePathArgs(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    path: str = Field(min_length=1, max_length=2048)


class PdfFormArgs(WorkspacePathArgs):
    fields: dict[str, Any] = Field(min_length=1, max_length=200)


class YouTubeArgs(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    url: str = Field(min_length=1, max_length=2048)
    languages: list[str] = Field(default_factory=lambda: ["en.*", "en"], max_length=5)


class ImageEditArgs(WorkspacePathArgs):
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=10)


class VisualReportArgs(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=20_000)
    sections: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class SessionArtifactsArgs(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)


class ResearchStartArgs(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    query: str = Field(min_length=1, max_length=20_000)
    max_time: int = Field(default=300, ge=30, le=600)
    category: str | None = Field(default=None, max_length=80)


class ResearchStatusArgs(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)


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


def _tool_result(operation, *args, **kwargs) -> str:
    try:
        return json.dumps(operation(*args, **kwargs), ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


def ares_extract_pdf(session_id: str, path: str, **_kwargs) -> str:
    from api.ingestion import extract_pdf
    return _tool_result(extract_pdf, session_id, path)


def ares_fill_pdf_form(
    session_id: str, path: str, fields: dict[str, Any], **_kwargs
) -> str:
    from api.ingestion import fill_pdf_form
    return _tool_result(fill_pdf_form, session_id, path, fields)


def ares_ingest_youtube(
    session_id: str, url: str, languages: list[str] | None = None, **_kwargs
) -> str:
    from api.ingestion import ingest_youtube
    return _tool_result(ingest_youtube, session_id, url, languages)


def ares_edit_image(
    session_id: str, path: str, operations: list[dict[str, Any]], **_kwargs
) -> str:
    from api.generated_artifacts import edit_image
    return _tool_result(edit_image, session_id, path, operations)


def ares_create_visual_report(
    session_id: str,
    title: str,
    summary: str = "",
    sections: list[dict[str, Any]] | None = None,
    **_kwargs,
) -> str:
    from api.generated_artifacts import create_visual_report
    return _tool_result(
        create_visual_report,
        session_id,
        title=title,
        summary=summary,
        sections=sections or [],
    )


def ares_list_artifacts(session_id: str, **_kwargs) -> str:
    from api.workspace_artifacts import list_artifacts
    return _tool_result(list_artifacts, session_id)


_RESEARCH_HANDLER = None


def _research_handler():
    global _RESEARCH_HANDLER
    if _RESEARCH_HANDLER is None:
        from api.research.handler import ResearchHandler
        _RESEARCH_HANDLER = ResearchHandler()
    return _RESEARCH_HANDLER


def ares_start_research(
    session_id: str,
    query: str,
    max_time: int = 300,
    category: str | None = None,
    **_kwargs,
) -> str:
    return _tool_result(
        _research_handler().start_research,
        session_id,
        query,
        max_time,
        category,
    )


def ares_get_research(session_id: str, **_kwargs) -> str:
    handler = _research_handler()
    return json.dumps({
        "session_id": session_id,
        "status": handler.get_status(session_id),
        "result": handler.get_result(session_id),
        "sources": handler.get_sources(session_id) or [],
    }, ensure_ascii=False, default=str)


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
    {
        "name": "ares_start_research",
        "description": "Start an ARES deep-research job using the selected runtime and configured search backend.",
        "fn": ares_start_research,
        "args_model": ResearchStartArgs,
    },
    {
        "name": "ares_get_research",
        "description": "Read the status, sources, and result of an ARES deep-research job.",
        "fn": ares_get_research,
        "args_model": ResearchStatusArgs,
    },
    {
        "name": "ares_extract_pdf",
        "description": "Extract text and form-field names from a PDF in the active session workspace.",
        "fn": ares_extract_pdf,
        "args_model": WorkspacePathArgs,
    },
    {
        "name": "ares_fill_pdf_form",
        "description": "Fill known fields in a workspace PDF and save the result as an ARES artifact.",
        "fn": ares_fill_pdf_form,
        "args_model": PdfFormArgs,
    },
    {
        "name": "ares_ingest_youtube",
        "description": "Acquire a YouTube transcript and save it in the active session workspace.",
        "fn": ares_ingest_youtube,
        "args_model": YouTubeArgs,
    },
    {
        "name": "ares_edit_image",
        "description": "Apply validated image operations and save the output as an ARES artifact.",
        "fn": ares_edit_image,
        "args_model": ImageEditArgs,
    },
    {
        "name": "ares_create_visual_report",
        "description": "Create a self-contained visual HTML report in the active session workspace.",
        "fn": ares_create_visual_report,
        "args_model": VisualReportArgs,
    },
    {
        "name": "ares_list_artifacts",
        "description": "List generated artifacts for an ARES session workspace.",
        "fn": ares_list_artifacts,
        "args_model": SessionArtifactsArgs,
    },
]
