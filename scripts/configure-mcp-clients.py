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
    command = str(python)
    args = [str(server_path)]
    stdio = {"command": command, "args": args}

    replace_cli("claude", ["claude", "mcp", "remove", "ares-system", "--scope", "user"],
                ["claude", "mcp", "add", "--scope", "user", "ares-system", "--", command, *args])
    # Retire the former direct host-tool bypass. Hermes reaches its scoped host
    # target through ARES/Agentgateway instead of granting every client a
    # second, independently governed tool plane.
    subprocess.run(
        ["claude", "mcp", "remove", "hermes-mac-tools", "--scope", "user"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ) if shutil.which("claude") else None
    replace_cli("codex", ["codex", "mcp", "remove", "ares-system"],
                ["codex", "mcp", "add", "ares-system", "--", command, *args])
    subprocess.run(
        ["codex", "mcp", "remove", "hermes-mac-tools"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ) if shutil.which("codex") else None
    replace_cli("gemini", ["gemini", "mcp", "remove", "--scope", "user", "ares-system"],
                ["gemini", "mcp", "add", "--scope", "user", "--description",
                 "ARES governed control plane", "ares-system", command, *args])

    home = Path.home()
    remove_json_entries(home / ".mcp.json", "mcpServers", {"hermes-mac-tools", "hermes-mac", "hermes-wsl"})
    remove_json_entries(home / ".claude" / ".mcp.json", "mcpServers", {"hermes-mac-tools", "hermes-mac", "hermes-wsl"})
    remove_json_entries(home / ".claude" / "mcp.json", "mcpServers", {"hermes-mac-tools", "hermes-mac", "hermes-wsl"})
    write_json(home / ".gemini" / "config" / "mcp_config.json", "mcpServers", stdio)
    write_json(home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json", "mcpServers", stdio)
    write_json(home / "Library" / "Application Support" / "Code" / "User" / "mcp.json", "servers", {"type": "stdio", **stdio})
    subprocess.run([str(python), str(repo / "scripts" / "probe-mcp-clients.py")], check=True)
    print("Configured installed clients to use the single ARES System MCP server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
