"""Identity-scoped, audited host capabilities for independently owned agents.

Agentgateway starts one copy of this stdio server per identity.  The identity
and grants are fixed by the parent process, not supplied by an MCP caller.
There is deliberately no arbitrary shell, delete, chmod, credential, or
unrestricted home-directory tool here.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # MCP SDK 2.x renamed the server implementation.
    from mcp.server.mcpserver import MCPServer as FastMCP


MAX_BYTES = 1_000_000
IDENTITY = os.environ.get("ARES_CAPABILITY_IDENTITY", "").strip()
GRANTS_PATH = Path(
    os.environ.get("ARES_CAPABILITY_GRANTS")
    or Path.home() / ".ares" / "capabilities" / "grants.json"
)
AUDIT_PATH = Path(
    os.environ.get("ARES_CAPABILITY_AUDIT")
    or Path.home() / ".ares" / "audit" / "host-capabilities.jsonl"
)
mcp = FastMCP(f"ares-host-{IDENTITY or 'invalid'}")


def _grant() -> dict[str, Any]:
    if IDENTITY not in {"admin", "hermes", "jaeger"}:
        raise PermissionError("host capability identity is missing or invalid")
    raw = json.loads(GRANTS_PATH.read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        raise RuntimeError("unsupported host-capability grant version")
    grant = (raw.get("identities") or {}).get(IDENTITY)
    if not isinstance(grant, dict):
        raise PermissionError(f"no host capability grant exists for {IDENTITY}")
    return grant


def _roots(grant: dict[str, Any] | None = None) -> list[Path]:
    value = grant or _grant()
    roots = [Path(str(item)).expanduser().resolve() for item in value.get("roots") or []]
    if not roots:
        raise PermissionError("identity has no workspace roots")
    return roots


def _require(capability: str) -> dict[str, Any]:
    grant = _grant()
    if capability not in set(grant.get("capabilities") or []):
        raise PermissionError(f"{IDENTITY} is not granted {capability}")
    return grant


def _resolve(path: str, *, must_exist: bool = True, capability: str = "") -> Path:
    grant = _grant()
    roots = _roots(grant)
    requested = str(path or "").strip()
    if not requested or requested == "/workspace":
        candidate = roots[0]
    elif requested.startswith("/workspace/"):
        candidate = roots[0] / requested.removeprefix("/workspace/")
    else:
        candidate = Path(requested).expanduser()
        if not candidate.is_absolute():
            candidate = roots[0] / candidate
    try:
        # Resolving the parent for a new file catches symlink escapes while
        # still permitting creation of the final path component.
        resolved = candidate.resolve(strict=must_exist)
        if not must_exist and not candidate.exists():
            resolved = candidate.parent.resolve(strict=True) / candidate.name
        if not any(resolved == root or root in resolved.parents for root in roots):
            raise PermissionError("path is outside this identity's approved workspace roots")
        return resolved
    except Exception as exc:
        if capability:
            _audit(
                capability, outcome="denied", requested_path=requested[:1024],
                error=type(exc).__name__,
            )
        raise


def _audit(capability: str, *, outcome: str, path: Path | None = None, **details: Any) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    AUDIT_PATH.parent.chmod(0o700)
    record = {
        "at": time.time(),
        "identity": IDENTITY,
        "capability": capability,
        "outcome": outcome,
        **({"path": str(path)} if path else {}),
        **details,
    }
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    fd = os.open(AUDIT_PATH, flags, 0o600)
    try:
        os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_readonly(args: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
        check=False,
    )
    stdout = completed.stdout[:MAX_BYTES]
    stderr = completed.stderr[:20_000]
    return {"exit_code": completed.returncode, "stdout": stdout, "stderr": stderr}


@mcp.tool()
def capabilities_inspect() -> dict[str, Any]:
    """Show this caller's identity, approved roots, and granted capabilities."""

    grant = _grant()
    result = {
        "identity": IDENTITY,
        "roots": [str(root) for root in _roots(grant)],
        "capabilities": sorted(set(grant.get("capabilities") or [])),
        "limits": {"max_file_bytes": MAX_BYTES, "arbitrary_shell": False, "delete": False},
    }
    _audit("capabilities.inspect", outcome="allowed")
    return result


@mcp.tool()
def workspace_list(path: str = "/workspace") -> list[dict[str, Any]]:
    """List one approved workspace directory without reading file contents."""

    capability = "workspace.list"
    _require(capability)
    target = _resolve(path, capability=capability)
    try:
        if not target.is_dir():
            raise NotADirectoryError(str(target))
        rows = []
        for item in sorted(target.iterdir(), key=lambda value: value.name.lower())[:1000]:
            stat = item.lstat()
            rows.append({
                "name": item.name,
                "kind": "link" if item.is_symlink() else ("directory" if item.is_dir() else "file"),
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            })
        _audit(capability, outcome="allowed", path=target, entries=len(rows))
        return rows
    except Exception as exc:
        _audit(capability, outcome="denied", path=target, error=type(exc).__name__)
        raise


@mcp.tool()
def workspace_read(path: str) -> dict[str, Any]:
    """Read one UTF-8 text file under an approved root (maximum 1 MB)."""

    capability = "workspace.read"
    _require(capability)
    target = _resolve(path, capability=capability)
    try:
        if not target.is_file():
            raise FileNotFoundError(str(target))
        data = target.read_bytes()
        if len(data) > MAX_BYTES:
            raise ValueError("file exceeds the 1 MB host-capability limit")
        text = data.decode("utf-8")
        result = {"path": str(target), "content": text, "bytes": len(data), "sha256": _sha256(data)}
        _audit(capability, outcome="allowed", path=target, bytes=len(data), sha256=result["sha256"])
        return result
    except Exception as exc:
        _audit(capability, outcome="denied", path=target, error=type(exc).__name__)
        raise


@mcp.tool()
def workspace_write(path: str, content: str, expected_sha256: str = "") -> dict[str, Any]:
    """Atomically write UTF-8 text under an approved root.

    Existing files require their current SHA-256 in ``expected_sha256`` to
    prevent silent overwrites. New files require an empty precondition.
    """

    capability = "workspace.write"
    _require(capability)
    raw = content.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("content exceeds the 1 MB host-capability limit")
    target = _resolve(path, must_exist=False, capability=capability)
    try:
        target.parent.mkdir(parents=False, exist_ok=True)
        if target.exists():
            if not target.is_file():
                raise ValueError("target is not a regular file")
            current = target.read_bytes()
            current_hash = _sha256(current)
            if not expected_sha256 or expected_sha256 != current_hash:
                raise RuntimeError(f"write precondition failed; current sha256 is {current_hash}")
        elif expected_sha256:
            raise RuntimeError("write precondition failed; target does not exist")
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        result = {"path": str(target), "bytes": len(raw), "sha256": _sha256(raw)}
        _audit(capability, outcome="allowed", path=target, bytes=len(raw), sha256=result["sha256"])
        return result
    except Exception as exc:
        _audit(capability, outcome="denied", path=target, error=type(exc).__name__)
        raise


@mcp.tool()
def workspace_mkdir(path: str) -> dict[str, Any]:
    """Create one directory below an approved root; parents must exist."""

    capability = "workspace.mkdir"
    _require(capability)
    target = _resolve(path, must_exist=False, capability=capability)
    try:
        target.mkdir(parents=False, exist_ok=False, mode=0o700)
        _audit(capability, outcome="allowed", path=target)
        return {"path": str(target), "created": True}
    except Exception as exc:
        _audit(capability, outcome="denied", path=target, error=type(exc).__name__)
        raise


def _git(path: str, args: list[str], capability: str) -> dict[str, Any]:
    _require(capability)
    target = _resolve(path, capability=capability)
    if target.is_file():
        target = target.parent
    command = [
        "/usr/bin/git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
        "-c", "diff.external=", "-c", "diff.trustExitCode=false", *args,
    ]
    result = _run_readonly(command, cwd=target)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed", path=target, exit_code=result["exit_code"])
    return result


@mcp.tool()
def git_status(path: str = "/workspace") -> dict[str, Any]:
    """Run a hook-disabled, read-only Git status in an approved workspace."""

    return _git(path, ["status", "--short", "--branch", "--untracked-files=normal"], "git.status")


@mcp.tool()
def git_diff(path: str = "/workspace") -> dict[str, Any]:
    """Read the working-tree Git diff without external diff drivers."""

    return _git(path, ["--no-pager", "diff", "--no-ext-diff", "--no-textconv"], "git.diff")


@mcp.tool()
def service_status() -> dict[str, Any]:
    """Probe the public health endpoints; this cannot start or stop services."""

    import urllib.error
    import urllib.request

    capability = "service.status"
    _require(capability)
    endpoints = {
        "ares": "http://127.0.0.1:8788/health",
        "jaeger": "http://127.0.0.1:8791/health",
        "ollama": "http://127.0.0.1:11434/api/tags",
        "n8n": "http://127.0.0.1:5678/healthz",
    }
    result: dict[str, Any] = {}
    for name, url in endpoints.items():
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                response.read(4096)
                result[name] = {"online": True, "http_status": response.status}
        except urllib.error.HTTPError as exc:
            result[name] = {"online": True, "http_status": exc.code}
        except Exception as exc:
            result[name] = {"online": False, "error": type(exc).__name__}
    _audit(capability, outcome="allowed")
    return result


if __name__ == "__main__":
    mcp.run()
