#!/usr/bin/env python3
"""Idempotently point installed MCP clients at the single ARES System server."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def write_json(path: Path, section: str, server: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.setdefault(section, {})["ares-system"] = server
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def remove_json_entries(path: Path, section: str, names: set[str]) -> None:
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get(section)
    if not isinstance(servers, dict) or not names.intersection(servers):
        return
    for name in names:
        servers.pop(name, None)
    write_json_document(path, data)


def write_json_document(path: Path, data: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def replace_cli(name: str, remove: list[str], add: list[str]) -> None:
    if not shutil.which(name):
        return
    subprocess.run(remove, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    subprocess.run(add, check=True)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    python = repo / "services" / "controller" / ".venv" / "bin" / "python"
    server_path = repo / "services" / "controller" / "system_mcp_server.py"
    if not python.is_file() or not server_path.is_file():
        raise SystemExit("ARES controller environment is incomplete")

    home = Path.home()
    token_file = home / ".ares" / "gateway" / "client.token"
    admin_token = token_file.read_text(encoding="utf-8").strip() if token_file.is_file() else ""
    gateway_url = "http://127.0.0.1:8811/mcp"

    command = str(python)
    args = [str(server_path)]
    stdio = {"command": command, "args": args}
    gateway_http = {
        "url": gateway_url,
        "headers": {"Authorization": f"Bearer {admin_token}"},
    }

    # Ensure ARES_GATEWAY_TOKEN is present in ~/.zshenv for CLI clients
    zshenv = home / ".zshenv"
    zshenv_text = zshenv.read_text(encoding="utf-8") if zshenv.exists() else ""
    if admin_token and "ARES_GATEWAY_TOKEN=" not in zshenv_text:
        with open(zshenv, "a", encoding="utf-8") as f:
            f.write(f'\nexport ARES_GATEWAY_TOKEN="{admin_token}"\n')

    # Claude Code: point at Agentgateway HTTP endpoint with bearer header
    if shutil.which("claude") and admin_token:
        replace_cli("claude", ["claude", "mcp", "remove", "ares-system", "--scope", "user"],
                    ["claude", "mcp", "add", "ares-system", gateway_url, "--transport", "http",
                     "--scope", "user", "-H", f"Authorization: Bearer {admin_token}"])
    else:
        replace_cli("claude", ["claude", "mcp", "remove", "ares-system", "--scope", "user"],
                    ["claude", "mcp", "add", "--scope", "user", "ares-system", "--", command, *args])

    # Retire former direct host-tool bypass
    subprocess.run(
        ["claude", "mcp", "remove", "hermes-mac-tools", "--scope", "user"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ) if shutil.which("claude") else None

    # Codex CLI: point at Agentgateway HTTP endpoint
    if shutil.which("codex") and admin_token:
        replace_cli("codex", ["codex", "mcp", "remove", "ares-system"],
                    ["codex", "mcp", "add", "ares-system", "--url", gateway_url,
                     "--bearer-token-env-var", "ARES_GATEWAY_TOKEN"])
    else:
        replace_cli("codex", ["codex", "mcp", "remove", "ares-system"],
                    ["codex", "mcp", "add", "ares-system", "--", command, *args])

    subprocess.run(
        ["codex", "mcp", "remove", "hermes-mac-tools"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ) if shutil.which("codex") else None

    # Gemini CLI: configure ares-system stdio wrapper
    replace_cli("gemini", ["gemini", "mcp", "remove", "--scope", "user", "ares-system"],
                ["gemini", "mcp", "add", "--scope", "user", "--description",
                 "ARES governed control plane", "ares-system", command, *args])

    remove_json_entries(home / ".mcp.json", "mcpServers", {"hermes-mac-tools", "hermes-mac", "hermes-wsl"})
    remove_json_entries(home / ".claude" / ".mcp.json", "mcpServers", {"hermes-mac-tools", "hermes-mac", "hermes-wsl"})
    remove_json_entries(home / ".claude" / "mcp.json", "mcpServers", {"hermes-mac-tools", "hermes-mac", "hermes-wsl"})
    write_json(home / ".gemini" / "config" / "mcp_config.json", "mcpServers", stdio)
    write_json(home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json", "mcpServers", gateway_http)
    write_json(home / "Library" / "Application Support" / "Code" / "User" / "mcp.json", "servers", {"type": "sse", **gateway_http})
    subprocess.run([str(python), str(repo / "scripts" / "probe-mcp-clients.py")], check=True)
    print("Configured installed clients to use the governed ARES Agentgateway on :8811.")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
