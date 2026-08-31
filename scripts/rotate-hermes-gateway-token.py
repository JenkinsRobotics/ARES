#!/usr/bin/env python3
"""Rotate Hermes' identity-scoped Agentgateway token without printing it.

The token remains materialized in two owner-controlled, mode-0600 files because
the Hermes container reads its environment from ``~/.hermes/.env`` and
Agentgateway's generator reads ``~/.hermes/ares/ares-mcp.token``. Hermes'
configuration stores only an environment reference, so future session records
cannot copy the live token from the MCP header configuration.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV_KEY = "MCP_ARES_HOST_API_KEY"
CONFIG_KEY = "mcp_servers.ares-host.headers.Authorization"
LAUNCHD_LABEL = "com.jenkinsrobotics.ares-agentgateway"
HERMES_CONTAINER = "hermes-webui-hermes-webui"


def atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def replace_env(path: Path, token: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f"{ENV_KEY}={token}"
    updated: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{ENV_KEY}="):
            if not replaced:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(line)
    if not replaced:
        updated.append(replacement)
    atomic_write(path, "\n".join(updated).rstrip() + "\n")


def run(*args: str) -> None:
    subprocess.run(args, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)


def set_hermes_reference() -> None:
    run(
        "hermes", "config", "set", "--force", CONFIG_KEY,
        f"Bearer ${{{ENV_KEY}}}",
    )


def configure_gateway(repo: Path) -> None:
    python = repo / "services" / "controller" / ".venv" / "bin" / "python"
    run(str(python), str(repo / "scripts" / "configure-system-fabric.py"))


def restart_gateway() -> None:
    run(
        "/bin/launchctl", "kickstart", "-k",
        f"gui/{os.getuid()}/{LAUNCHD_LABEL}",
    )


def probe(token: str) -> int:
    request = urllib.request.Request(
        "http://127.0.0.1:8811/mcp",
        data=(
            b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
            b'{"protocolVersion":"2025-03-26","capabilities":{},'
            b'"clientInfo":{"name":"ares-rotation-probe","version":"1"}}}'
        ),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read(4096)
            return response.status
    except urllib.error.HTTPError as exc:
        exc.read(4096)
        return exc.code


def wait_for_new_token(new_token: str, old_token: str) -> None:
    deadline = time.monotonic() + 30
    last_new = 0
    while time.monotonic() < deadline:
        try:
            last_new = probe(new_token)
            if last_new == 200 and probe(old_token) == 401:
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    raise RuntimeError(
        f"gateway token verification failed (new token HTTP {last_new}; old token was not rejected)"
    )


def restart_hermes() -> None:
    run("container", "stop", HERMES_CONTAINER)
    run("container", "start", HERMES_CONTAINER)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    home = Path.home()
    token_path = home / ".hermes" / "ares" / "ares-mcp.token"
    env_path = home / ".hermes" / ".env"
    if not token_path.exists():
        raise SystemExit(f"Hermes gateway token is missing: {token_path}")
    old_token = token_path.read_text(encoding="utf-8").strip()
    if not old_token:
        raise SystemExit("Hermes gateway token is empty")
    old_env = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    new_token = secrets.token_urlsafe(32)
    try:
        atomic_write(token_path, new_token + "\n")
        replace_env(env_path, new_token)
        set_hermes_reference()
        configure_gateway(repo)
        restart_gateway()
        wait_for_new_token(new_token, old_token)
        restart_hermes()
    except Exception:
        atomic_write(token_path, old_token + "\n")
        atomic_write(env_path, old_env)
        try:
            set_hermes_reference()
            configure_gateway(repo)
            restart_gateway()
        except Exception as rollback_error:
            print(f"Token rotation and rollback failed: {type(rollback_error).__name__}", file=sys.stderr)
        raise

    print("Rotated Hermes Agentgateway credential; old credential returns HTTP 401.")
    print("Hermes MCP configuration now stores an environment reference, not the live token.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
