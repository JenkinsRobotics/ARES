"""Canonical, secret-free integration catalog owned by the ARES control plane."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

_CATALOG = (
    {"id": "claude-code", "kind": "mcp-client", "command": "claude", "mode": "available", "risk": "local-tools"},
    {"id": "codex", "kind": "mcp-client", "command": "codex", "mode": "available", "risk": "local-tools"},
    {"id": "gemini", "kind": "mcp-client", "command": "gemini", "mode": "available", "risk": "local-tools"},
    {"id": "grok", "kind": "terminal-tool", "command": "grok", "mode": "read-only", "risk": "local-tools"},
    {"id": "pi", "kind": "terminal-tool", "command": "pi", "mode": "read-only", "risk": "local-tools"},
    {"id": "vscode", "kind": "mcp-client", "command": "code", "mode": "available", "risk": "local-tools"},
    {"id": "antigravity", "kind": "mcp-client-candidate", "application": "/Applications/Antigravity IDE.app", "mode": "available", "risk": "local-tools"},
    {"id": "docker-mcp", "kind": "alternate-gateway", "command": "docker", "mode": "disabled", "risk": "competing-gateway"},
    {"id": "notion", "kind": "remote-mcp", "mode": "approval-required", "risk": "oauth-read-write"},
    {"id": "google-workspace", "kind": "remote-mcp", "mode": "approval-required", "risk": "oauth-read-write"},
    {"id": "github", "kind": "remote-mcp", "command": "gh", "mode": "available", "risk": "repository-write"},
    {"id": "obsidian", "kind": "adapter-candidate", "mode": "disabled", "risk": "vault-files"},
    {"id": "xcode", "kind": "adapter-candidate", "command": "xcodebuild", "mode": "available", "risk": "build-sign-publish"},
    {"id": "shortcuts", "kind": "adapter-candidate", "command": "shortcuts", "mode": "available", "risk": "host-automation"},
)


def integration_catalog() -> dict[str, Any]:
    """Discover clients without starting or authorizing integrations."""
    def installed(command: str) -> bool:
        if shutil.which(command):
            return True
        if any(
            (root / command).is_file()
            for root in (Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/usr/bin"))
        ):
            return True
        return any(
            (root / command).is_file()
            for root in (Path.home() / ".local" / "bin", Path.home() / "bin", Path.home() / ".grok" / "bin")
        )

    state = Path(os.environ.get("ARES_HOME") or Path.home() / ".ares")
    evidence_path = state / "integrations" / "status.json"
    evidence: dict[str, Any] = {}
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence = payload.get("integrations") if isinstance(payload.get("integrations"), dict) else {}
    except (OSError, json.JSONDecodeError, AttributeError):
        evidence = {}

    rows = []
    for entry in _CATALOG:
        command = str(entry.get("command") or "")
        application = str(entry.get("application") or "")
        is_installed = installed(command) if command else (Path(application).is_dir() if application else None)
        observed = evidence.get(entry["id"]) if isinstance(evidence.get(entry["id"]), dict) else {}
        state_name = str(observed.get("state") or ("installed" if is_installed else "not-installed"))
        rows.append({
            **entry,
            "installed": is_installed,
            "state": state_name,
            "configured": observed.get("configured"),
            "connected": observed.get("connected"),
            "invocation_tested": observed.get("invocation_tested", False),
            "detail": str(observed.get("detail") or ""),
            "last_tested_at": observed.get("tested_at"),
            "authority": "ares",
            "gateway": "agentgateway" if entry["kind"] != "alternate-gateway" else None,
        })
    return {
        "version": 1,
        "strategy": "single-ares-gateway",
        "network_gateway": "agentgateway",
        "alternate_gateways_enabled": False,
        "evidence_path": str(evidence_path),
        "integrations": rows,
    }
