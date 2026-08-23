"""FastAPI endpoints for ARES Cognitive Operating Modes and Codebase Symbol Maps."""

from __future__ import annotations

from typing import Annotated, Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..request_context import RequestIdentity, require_identity, require_mutation_identity
from api.ares_tools import (
    ares_get_mode,
    ares_set_mode,
    ares_trigger_dream,
    ares_get_repo_map,
    dispatch_ares_tool,
)

router = APIRouter(prefix="/api", tags=["modes"])


class ModeSwitchRequest(BaseModel):
    mode: str = Field(..., description="Target mode: 'standby', 'focus', or 'wonder'")
    session_id: str | None = Field(default=None, description="Optional session ID when entering focus mode")


class DreamTriggerRequest(BaseModel):
    workspaces: list[str] | None = Field(default=None, description="Optional target workspace paths")


class ToolExecuteRequest(BaseModel):
    tool: str = Field(..., description="ARES tool name")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


@router.get("/modes/status")
def get_modes_status(
    identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Retrieve current ARES cognitive operating mode and dream reflection state."""
    return ares_get_mode()


@router.post("/modes/switch")
def switch_mode(
    payload: ModeSwitchRequest,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Transition to a new cognitive operating mode (standby, focus, wonder)."""
    return ares_set_mode(payload.mode)


@router.post("/modes/dream/trigger")
def trigger_dream(
    payload: DreamTriggerRequest,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Trigger an on-demand Wonder/Dream reflection & AST indexing cycle."""
    return ares_trigger_dream(payload.workspaces)


@router.get("/repomap")
def get_repomap(
    identity: Annotated[RequestIdentity, Depends(require_identity)],
    workspace: str = "",
    max_files: int = 50,
):
    """Generate an AST codebase symbol map for the specified workspace."""
    return ares_get_repo_map(workspace or None, max_files=max_files)


@router.post("/tools/execute")
def execute_ares_tool(
    payload: ToolExecuteRequest,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Execute an ARES controller tool programmatically."""
    return dispatch_ares_tool(payload.tool, payload.args)


__all__ = ["router"]
