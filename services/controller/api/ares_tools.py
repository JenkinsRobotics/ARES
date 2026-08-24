"""ARES Controller Toolpack.

Provides first-class programmatic tools for ARES agent self-management:
- Workspace registration & listing
- Cognitive mode switching (Standby, Focus, Wonder)
- Dream/Wonder reflection cycles
- Memory updates
- Codebase AST repo map generation
- Test suite verification execution
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.modes import CognitiveMode, get_mode_manager
from core.knowledge.repomap import build_workspace_repomap

logger = logging.getLogger(__name__)


# ── Tool argument models ──────────────────────────────────────────────────
# Every tool in ARES_TOOL_DEFS carries an args_model so MCP discovery and the
# JaegerAI ToolDef bridge can publish a real JSON Schema instead of an empty
# object. Field constraints are the tool boundary's first validation pass.


class AddWorkspaceArgs(BaseModel):
    path: str = Field(min_length=1, max_length=4096, description="Absolute path to register as a workspace")
    name: str | None = Field(default=None, max_length=256, description="Optional display name for the workspace")


class NoArgs(BaseModel):
    """No arguments."""


class SetModeArgs(BaseModel):
    mode: str = Field(min_length=1, max_length=32, description="Cognitive mode: standby, focus, or wonder")


class TriggerDreamArgs(BaseModel):
    workspaces: list[str] | None = Field(
        default=None,
        max_length=64,
        description="Workspace paths to reflect over; defaults to all registered workspaces",
    )


class WriteMemoryNoteArgs(BaseModel):
    section: str = Field(min_length=1, max_length=32, description="Memory file to write: memory, user, or soul")
    content: str = Field(min_length=1, max_length=65536, description="Content to append to the memory file")


class RepoMapArgs(BaseModel):
    workspace: str | None = Field(default=None, max_length=4096, description="Workspace path; defaults to the active workspace")
    max_files: int = Field(default=50, ge=1, le=2000, description="Maximum number of files to include in the map")


class RunVerificationArgs(BaseModel):
    workspace: str | None = Field(default=None, max_length=4096, description="Workspace path; defaults to the active workspace")


def ares_add_workspace(path: str, name: str | None = None) -> dict[str, Any]:
    """Add a new directory as a registered ARES workspace."""
    from api.workspace import load_workspaces, save_workspaces, validate_workspace_to_add

    try:
        resolved = validate_workspace_to_add(path)
        workspaces = load_workspaces()
        if any(item["path"] == str(resolved) for item in workspaces):
            return {
                "ok": False,
                "error": f"Workspace '{resolved}' is already registered.",
                "workspaces": workspaces,
            }
        ws_name = (name or "").strip() or resolved.name or str(resolved)
        workspaces.append({"path": str(resolved), "name": ws_name})
        save_workspaces(workspaces)
        logger.info("ARES workspace added: %s (%s)", ws_name, resolved)
        return {
            "ok": True,
            "message": f"Successfully registered workspace '{ws_name}' at {resolved}",
            "workspaces": workspaces,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ares_list_workspaces() -> dict[str, Any]:
    """List all registered ARES workspaces."""
    from api.workspace import load_workspaces

    try:
        workspaces = load_workspaces()
        return {
            "ok": True,
            "count": len(workspaces),
            "workspaces": workspaces,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ares_set_mode(mode: str) -> dict[str, Any]:
    """Switch ARES cognitive operating mode (standby, focus, wonder)."""
    try:
        mgr = get_mode_manager()
        state = mgr.switch_mode(mode)
        return {
            "ok": True,
            "message": f"Cognitive mode switched to '{state.current_mode.value}'",
            "state": state.as_dict(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ares_get_mode() -> dict[str, Any]:
    """Get the current ARES cognitive operating mode and dream statistics."""
    try:
        mgr = get_mode_manager()
        return {
            "ok": True,
            "state": mgr.state.as_dict(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ares_trigger_dream(workspaces: list[str] | None = None) -> dict[str, Any]:
    """Trigger an on-demand Wonder/Dream reflection cycle to index codebase symbols and synthesize knowledge."""
    try:
        mgr = get_mode_manager()
        report = mgr.trigger_dream_cycle(workspaces)
        return {
            "ok": report.status == "completed",
            "report": report.as_dict(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ares_write_memory_note(section: str, content: str) -> dict[str, Any]:
    """Write content directly to an ARES memory file ('memory', 'user', or 'soul')."""
    from api.memory_store import write_memory

    try:
        res = write_memory(section, content)
        return {"ok": True, "result": res}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ares_get_repo_map(workspace: str | None = None, max_files: int = 50) -> dict[str, Any]:
    """Generate an AST codebase symbol map for a workspace."""
    try:
        if not workspace:
            from api.models import get_last_workspace
            workspace = os.environ.get("TERMINAL_CWD", "") or get_last_workspace() or str(Path.cwd())

        repomap = build_workspace_repomap(workspace, max_files=max_files)
        return {
            "ok": True,
            "workspace": repomap["workspace"],
            "scanned_files": repomap["scanned_files"],
            "total_symbols": repomap["total_symbols"],
            "formatted_map": repomap["formatted_map"],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ares_run_verification(workspace: str | None = None) -> dict[str, Any]:
    """Automatically detect and run tests for the active workspace."""
    try:
        target_dir = Path(workspace or Path.cwd()).expanduser().resolve()
        if not target_dir.is_dir():
            return {"ok": False, "error": f"Directory not found: {target_dir}"}

        # Detect test framework
        cmd: list[str] = []
        if (target_dir / "Package.swift").exists():
            cmd = ["swift", "test"]
        elif (target_dir / "pytest.ini").exists() or (target_dir / "pyproject.toml").exists() or (target_dir / "setup.py").exists():
            cmd = ["python3", "-m", "pytest", "-q"]
        elif (target_dir / "package.json").exists():
            cmd = ["npm", "test"]
        elif (target_dir / "Cargo.toml").exists():
            cmd = ["cargo", "test"]
        else:
            return {
                "ok": False,
                "error": "No recognized test configuration (Package.swift, pytest, package.json, Cargo.toml) found in workspace.",
            }

        res = subprocess.run(
            cmd,
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )

        return {
            "ok": res.returncode == 0,
            "command": " ".join(cmd),
            "returncode": res.returncode,
            "stdout": res.stdout[:4000],
            "stderr": res.stderr[:4000],
            "passed": res.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Test run timed out after 120s"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Canonical tool catalog ────────────────────────────────────────────────
# ARES_TOOL_DEFS is the single registration point for ARES-owned tools
# (AGENTS.md rule 4). The MCP boundary, the JaegerAI ToolDef bridge, the
# dynamic inventory route, and dispatch below all read this one list, so a
# tool added here shows up everywhere without a second edit.
ARES_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "ares_add_workspace",
        "description": "Add a new directory as a registered ARES workspace.",
        "fn": ares_add_workspace,
        "args_model": AddWorkspaceArgs,
    },
    {
        "name": "ares_list_workspaces",
        "description": "List all registered ARES workspaces.",
        "fn": ares_list_workspaces,
        "args_model": NoArgs,
    },
    {
        "name": "ares_set_mode",
        "description": "Switch the ARES cognitive operating mode (standby, focus, wonder).",
        "fn": ares_set_mode,
        "args_model": SetModeArgs,
    },
    {
        "name": "ares_get_mode",
        "description": "Get the current ARES cognitive operating mode and dream statistics.",
        "fn": ares_get_mode,
        "args_model": NoArgs,
    },
    {
        "name": "ares_trigger_dream",
        "description": (
            "Trigger an on-demand Wonder/Dream reflection cycle to index codebase "
            "symbols and synthesize knowledge."
        ),
        "fn": ares_trigger_dream,
        "args_model": TriggerDreamArgs,
    },
    {
        "name": "ares_write_memory_note",
        "description": "Write content directly to an ARES memory file ('memory', 'user', or 'soul').",
        "fn": ares_write_memory_note,
        "args_model": WriteMemoryNoteArgs,
    },
    {
        "name": "ares_get_repo_map",
        "description": "Generate an AST codebase symbol map for a workspace.",
        "fn": ares_get_repo_map,
        "args_model": RepoMapArgs,
    },
    {
        "name": "ares_run_verification",
        "description": "Automatically detect and run the test suite for the active workspace.",
        "fn": ares_run_verification,
        "args_model": RunVerificationArgs,
    },
]

# Name -> callable map for dynamic dispatch, derived so it cannot drift.
ARES_TOOLS_REGISTRY: dict[str, Any] = {
    str(definition["name"]): definition["fn"] for definition in ARES_TOOL_DEFS
}


def dispatch_ares_tool(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Execute an ARES controller tool by name."""
    fn = ARES_TOOLS_REGISTRY.get(tool_name)
    if fn is None:
        return {"ok": False, "error": f"Unknown ARES tool: {tool_name}"}
    return fn(**kwargs)
