"""Canonical inventory and catalog of all ARES MCP servers, tools, and capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def get_mcp_catalog() -> dict[str, Any]:
    """Return the authoritative, up-to-date catalog of all MCP servers, tools, and capabilities."""
    servers: list[dict[str, Any]] = []

    # 1. ares-system
    system_tools = [
        {
            "name": "system_status",
            "description": "Return the safe ARES control-plane status and recent run summary.",
            "parameters": {},
            "capability": None,
        },
        {
            "name": "system_metrics",
            "description": "Read current CPU, RAM, swap, disk, Ollama, and Jaeger telemetry.",
            "parameters": {
                "include_processes": {"type": "boolean", "default": True},
                "process_limit": {"type": "integer", "default": 10},
            },
            "capability": None,
        },
        {
            "name": "agents_list",
            "description": "List independently owned agents registered with ARES.",
            "parameters": {},
            "capability": None,
        },
        {
            "name": "integrations_list",
            "description": "Return ARES' canonical integration catalog and activation state.",
            "parameters": {},
            "capability": None,
        },
        {
            "name": "system_message",
            "description": "Create a durable goal and delegate it to Hermes or JaegerAI.",
            "parameters": {
                "message": {"type": "string", "required": True},
                "agent_id": {"type": "string", "default": "hermes"},
                "wait_seconds": {"type": "integer", "default": 0},
            },
            "capability": None,
        },
        {
            "name": "run_status",
            "description": "Return one ARES run and its immutable evidence events.",
            "parameters": {"run_id": {"type": "string", "required": True}},
            "capability": None,
        },
        {
            "name": "run_cancel",
            "description": "Safely request cancellation of an active ARES run.",
            "parameters": {"run_id": {"type": "string", "required": True}},
            "capability": None,
        },
        {
            "name": "approval_respond",
            "description": "Approve or deny one pending consequential action.",
            "parameters": {
                "approval_id": {"type": "string", "required": True},
                "decision": {"type": "string", "enum": ["approved", "denied"], "required": True},
            },
            "capability": None,
        },
        {
            "name": "approval_preview",
            "description": "Dry-run one approval request without granting or executing anything.",
            "parameters": {"approval_id": {"type": "string", "required": True}},
            "capability": None,
        },
    ]

    servers.append({
        "id": "ares-system",
        "name": "ARES System Control Plane",
        "transport": "stdio",
        "entrypoint": "services/controller/system_mcp_server.py",
        "gateway_target": "system",
        "gateway_url": "http://127.0.0.1:8811/mcp",
        "description": "Governed automation control plane for goals, runs, status, and approvals.",
        "auth": "Strict bearer token (~/.ares/gateway/client.token)",
        "tool_count": len(system_tools),
        "tools": system_tools,
    })

    # 2. ares-host
    host_tools = [
        {"name": "capabilities_inspect", "capability": "capabilities.inspect", "description": "Show this caller's identity, approved roots, and granted capabilities."},
        {"name": "capability_request", "capability": "capability.request", "description": "Ask ARES to create a human-reviewed, informed capability approval."},
        {"name": "workspace_list", "capability": "workspace.list", "description": "List one approved workspace directory without reading file contents."},
        {"name": "workspace_read", "capability": "workspace.read", "description": "Read one UTF-8 text file under an approved root (maximum 1 MB)."},
        {"name": "workspace_write", "capability": "workspace.write", "description": "Atomically write UTF-8 text under an approved root (requires SHA-256 for overwrites)."},
        {"name": "workspace_mkdir", "capability": "workspace.mkdir", "description": "Create one directory below an approved root; parents must exist."},
        {"name": "workspace_move", "capability": "workspace.move", "description": "Preview or atomically move one item within approved roots."},
        {"name": "calendar_list", "capability": "calendar.list", "description": "List upcoming Apple Calendar events using injection-safe JXA."},
        {"name": "calendar_create", "capability": "calendar.create", "description": "Preview or create exactly one Calendar event after one-shot ARES approval."},
        {"name": "notes_list", "capability": "notes.list", "description": "List Apple Notes titles and metadata without returning note bodies."},
        {"name": "notes_read", "capability": "notes.read", "description": "Read one Apple Note by exact title or owner-issued id."},
        {"name": "notes_create", "capability": "notes.create", "description": "Preview or create one Apple Note after one-shot ARES approval."},
        {"name": "reminders_list", "capability": "reminders.list", "description": "List reminders from Apple Reminders."},
        {"name": "reminders_create", "capability": "reminders.create", "description": "Preview or create one reminder after one-shot ARES approval."},
        {"name": "shortcuts_list", "capability": "shortcuts.list", "description": "List installed Apple Shortcuts without running them."},
        {"name": "shortcuts_run", "capability": "shortcuts.run", "description": "Preview or run one named Apple Shortcut after one-shot ARES approval."},
        {"name": "git_status", "capability": "git.status", "description": "Run a hook-disabled, read-only Git status in an approved workspace."},
        {"name": "git_diff", "capability": "git.diff", "description": "Read the working-tree Git diff without external diff drivers."},
        {"name": "service_status", "capability": "service.status", "description": "Probe public health endpoints of ARES, Jaeger, Ollama, and n8n."},
        {"name": "camera_status", "capability": "camera.status", "description": "Inspect connected camera status, AVFoundation indices, and gimbal orientation."},
        {"name": "camera_snapshot", "capability": "camera.snapshot", "description": "Capture a single frame (1080p/4K) from the camera as visual input."},
        {"name": "camera_listen", "capability": "camera.listen", "description": "Record audio (48 kHz mono WAV) from the camera beamforming microphone."},
        {"name": "camera_ptz", "capability": "camera.ptz", "description": "Control camera motorized gimbal: 'center', 'deskview', 'aim', or 'status'."},
    ]

    servers.append({
        "id": "ares-host",
        "name": "ARES Host Capability & Perception Plane",
        "transport": "stdio",
        "entrypoint": "services/controller/host_capability_mcp_server.py",
        "gateway_target": "host-hermes",
        "gateway_url": "http://127.0.0.1:8811/mcp",
        "description": "Identity-scoped host workspace confinement, Apple ecosystem tools, and hardware perception (camera, mic, gimbal).",
        "auth": "Identity-scoped grants in ~/.ares/capabilities/grants.json; immutable JSONL audit",
        "tool_count": len(host_tools),
        "tools": host_tools,
    })

    # 3. ares-webui
    webui_tools = [
        {"name": "list_projects", "description": "List session projects (scoped to active profile)."},
        {"name": "create_project", "description": "Create a new project for organizing sessions."},
        {"name": "rename_project", "description": "Rename a project and change its color."},
        {"name": "delete_project", "description": "Delete a project and unassign all its sessions."},
        {"name": "rename_session", "description": "Rename a session in the WebUI sidebar."},
        {"name": "move_session", "description": "Assign a session to a project or unassign."},
        {"name": "list_sessions", "description": "List sessions filtered by project or unassigned."},
        {"name": "ares_get_runtime_context", "description": "Get active backend, capabilities, open tasks, and embodiment state."},
        {"name": "ares_create_task", "description": "Create a new ARES task in the canonical task store."},
        {"name": "ares_update_task", "description": "Update task status (open, in_progress, blocked, done)."},
        {"name": "ares_start_research", "description": "Start an ARES deep-research job using selected runtime."},
        {"name": "ares_get_research", "description": "Read status, sources, and result of an ARES deep-research job."},
        {"name": "ares_extract_pdf", "description": "Extract text and form-field names from a PDF."},
        {"name": "ares_fill_pdf_form", "description": "Fill known fields in a workspace PDF and save artifact."},
        {"name": "ares_ingest_youtube", "description": "Acquire YouTube transcript and save in workspace."},
        {"name": "ares_edit_image", "description": "Apply image operations and save output artifact."},
        {"name": "ares_create_visual_report", "description": "Create self-contained HTML visual report."},
        {"name": "ares_list_artifacts", "description": "List generated artifacts for an ARES session workspace."},
    ]

    servers.append({
        "id": "ares-webui",
        "name": "ARES WebUI Session & Task Tools",
        "transport": "stdio",
        "entrypoint": "services/controller/mcp_server.py",
        "gateway_target": None,
        "gateway_url": None,
        "description": "Session/project management, deep research, PDF form filling, media ingest, and canonical task operations.",
        "auth": "Loopback / WebUI session",
        "tool_count": len(webui_tools),
        "tools": webui_tools,
    })

    # 4. ares-native-mcp
    native_tools = [
        {"name": "calendar", "description": "macOS EventKit calendar event management."},
        {"name": "contacts", "description": "macOS Contacts framework integration."},
        {"name": "file_operations", "description": "Local filesystem operations."},
        {"name": "image_generation", "description": "CoreImage / ML image generation."},
        {"name": "math_operations", "description": "Numerical computation and evaluation."},
        {"name": "memory_operations", "description": "Long-term episodic/semantic memory store."},
        {"name": "notes", "description": "macOS Apple Notes integration."},
        {"name": "screen_read", "description": "macOS ScreenCaptureKit display capture."},
        {"name": "spotlight", "description": "macOS CoreSpotlight search indexing."},
        {"name": "todo_operations", "description": "macOS Reminders integration."},
        {"name": "user_collaboration", "description": "macOS Notification and collaboration."},
        {"name": "weather", "description": "macOS WeatherKit live weather information."},
    ]

    servers.append({
        "id": "ares-native-mcp",
        "name": "ARES Native macOS Helper",
        "transport": "stdio",
        "entrypoint": "apps/macos/Sources/ARESNativeMCP/main.swift",
        "gateway_target": None,
        "gateway_url": None,
        "description": "Native macOS Swift framework tool plane for system integrations.",
        "auth": "macOS TCC permissions (Calendar, Contacts, Reminders, Screen Recording)",
        "tool_count": len(native_tools),
        "tools": native_tools,
    })

    # 5. jaeger-mcp-proxy
    servers.append({
        "id": "jaeger-mcp-proxy",
        "name": "Jaeger MCP Proxy",
        "transport": "stdio-bridge",
        "entrypoint": "services/controller/jaeger_mcp_proxy.py",
        "gateway_target": None,
        "gateway_url": None,
        "description": "Direct bridge to Jaeger companion MCP tools.",
        "auth": "Loopback IPC",
        "tool_count": len(host_tools),
        "tools": host_tools,
    })

    total_tools = sum(s["tool_count"] for s in servers)

    return {
        "ok": True,
        "version": 1,
        "total_servers": len(servers),
        "total_tools": total_tools,
        "servers": servers,
        "gateway": {
            "name": "agentgateway",
            "port": 8811,
            "endpoint": "http://127.0.0.1:8811/mcp",
            "auth_mode": "strict-bearer",
            "client_token_path": str(Path.home() / ".ares" / "gateway" / "client.token"),
            "federated_targets": [
                {"target": "system", "server_id": "ares-system", "prefix": "system_*"},
                {"target": "host-hermes", "server_id": "ares-host", "prefix": "host-hermes_*"},
            ],
        },
    }
