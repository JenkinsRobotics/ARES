#!/usr/bin/env python3
"""Record bounded, secret-free evidence for installed ARES MCP clients."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def execute(args: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        result = subprocess.run(
            args, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return result.returncode, (result.stdout + "\n" + result.stderr)[:200_000]
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, type(exc).__name__


def configured_json(path: Path, section: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload.get(section), dict) and "ares-system" in payload[section]


def main() -> int:
    tested_at = time.time()
    result: dict[str, dict[str, object]] = {}
    home = Path.home()
    state = Path(os.environ.get("ARES_HOME") or home / ".ares")
    output_path = state / "integrations" / "status.json"
    existing: dict[str, dict[str, object]] = {}
    try:
        prior = json.loads(output_path.read_text(encoding="utf-8"))
        rows = prior.get("integrations") if isinstance(prior, dict) else {}
        if isinstance(rows, dict):
            existing = {
                str(key): value for key, value in rows.items()
                if isinstance(value, dict)
            }
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    if shutil.which("claude"):
        code, output = execute(["claude", "mcp", "list"])
        configured = "ares-system:" in output
        connected = configured and "ares-system:" in output and "Connected" in output.split("ares-system:", 1)[1].splitlines()[0]
        result["claude-code"] = {
            "state": "connected" if connected else ("configured" if configured else "installed"),
            "configured": configured, "connected": connected,
            "invocation_tested": False, "tested_at": tested_at,
            "detail": "ARES System MCP health reported connected by Claude." if connected else f"Claude MCP list exited {code}.",
        }

    if shutil.which("codex"):
        code, output = execute(["codex", "mcp", "list"])
        configured = any(line.lstrip().startswith("ares-system ") for line in output.splitlines())
        enabled = configured and "enabled" in next(
            (line for line in output.splitlines() if line.lstrip().startswith("ares-system ")), "",
        ).lower()
        result["codex"] = {
            "state": "configured" if enabled else ("disabled" if configured else "installed"),
            "configured": configured, "connected": None,
            "invocation_tested": False, "tested_at": tested_at,
            "detail": "Configured and enabled; Codex list does not perform an MCP invocation." if enabled else f"Codex MCP list exited {code}.",
        }

    if shutil.which("gemini"):
        code, output = execute(["gemini", "mcp", "list"])
        configured = "ares-system:" in output
        disabled = "folder is untrusted" in output or " - Disabled" in output
        state = "disabled" if disabled else ("configured" if configured else "installed")
        detail = "Configured but suppressed in the current untrusted workspace." if disabled else f"Gemini MCP list exited {code}."
        if configured:
            trusted_code, trusted_output = execute(["gemini", "--skip-trust", "mcp", "list"])
            if "IneligibleTierError" in trusted_output or "no longer supported" in trusted_output:
                state = "blocked"
                detail = "Configured, but the installed Gemini CLI account tier is no longer eligible; use Antigravity or re-authenticate a supported account."
            elif trusted_code == 0 and "ares-system:" in trusted_output:
                state = "connected" if "Connected" in trusted_output else "configured"
                detail = "ARES System MCP is visible in a trusted Gemini session."
        result["gemini"] = {
            "state": state, "configured": configured,
            "connected": state == "connected", "invocation_tested": False,
            "tested_at": tested_at, "detail": detail,
        }

    vscode_configured = configured_json(
        home / "Library" / "Application Support" / "Code" / "User" / "mcp.json",
        "servers",
    )
    result["vscode"] = {
        "state": "configured" if vscode_configured else "installed",
        "configured": vscode_configured, "connected": None,
        "invocation_tested": False, "tested_at": tested_at,
        "detail": "ARES System MCP is present in VS Code's user configuration." if vscode_configured else "No ARES System MCP entry found.",
    }
    antigravity_installed = Path("/Applications/Antigravity IDE.app").is_dir()
    result["antigravity"] = {
        "state": "installed" if antigravity_installed else "not-installed",
        "configured": False, "connected": None,
        "invocation_tested": False, "tested_at": tested_at,
        "detail": "Installed; no stable user-level generic MCP configuration was discovered." if antigravity_installed else "Application not found.",
    }

    # A list/health probe cannot disprove a prior client-originated invocation.
    # Preserve that stronger evidence until a future invocation explicitly
    # fails; otherwise every inventory refresh would regress "connected" back
    # to merely "configured".
    for integration_id, row in result.items():
        prior = existing.get(integration_id) or {}
        if prior.get("invocation_tested") is True:
            row["invocation_tested"] = True
            row["connected"] = True
            row["state"] = "connected"
            row["tested_at"] = max(
                float(row.get("tested_at") or 0),
                float(prior.get("tested_at") or 0),
            )
            if prior.get("detail"):
                row["detail"] = str(prior["detail"])

    output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".status.", dir=output_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "tested_at": tested_at, "integrations": result}, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, output_path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
