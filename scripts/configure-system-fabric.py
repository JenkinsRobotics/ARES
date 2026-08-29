#!/usr/bin/env python3
"""Generate the machine-local Agentgateway configuration from discovered paths."""

from __future__ import annotations

import os
import hashlib
import secrets
import shutil
from pathlib import Path

import yaml


def executable(*candidates: Path | str) -> str:
    for candidate in candidates:
        raw = str(candidate)
        found = shutil.which(raw) if os.sep not in raw else raw
        if found and Path(found).is_file() and os.access(found, os.X_OK):
            # Preserve virtual-environment launcher paths. Resolving the Python
            # symlink would bypass the venv and lose its installed MCP/runtime
            # packages.
            return str(Path(found).absolute())
    raise SystemExit(f"Required executable was not found: {', '.join(map(str, candidates))}")


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    state = Path(os.environ.get("ARES_HOME") or Path.home() / ".ares")
    gateway_dir = state / "gateway"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    gateway_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    gateway_dir.chmod(0o700)
    output = gateway_dir / "config.yaml"
    token_path = gateway_dir / "client.token"
    if token_path.exists():
        client_token = token_path.read_text(encoding="utf-8").strip()
    else:
        client_token = secrets.token_urlsafe(32)
        token_path.write_text(client_token + "\n", encoding="utf-8")
        token_path.chmod(0o600)
    if not client_token:
        raise SystemExit(f"Gateway client token is empty: {token_path}")
    api_key_policy = {
        "keys": [{"keyHash": f"sha256:{hashlib.sha256(client_token.encode()).hexdigest()}"}],
        "mode": "strict",
    }

    controller_python = executable(repo / "services" / "controller" / ".venv" / "bin" / "python")
    hermes = executable(Path.home() / "bin" / "hermes", "hermes")
    config = {
        "config": {
            "database": {"url": f"sqlite://{gateway_dir / 'data.db'}"},
            "logging": {"format": "json"},
        },
        "mcp": {
            "port": 8811,
            "policies": {
                "apiKey": api_key_policy,
                "cors": {
                    "allowOrigins": ["http://127.0.0.1", "http://localhost"],
                    "allowHeaders": ["mcp-protocol-version", "content-type", "cache-control", "mcp-session-id"],
                    "exposeHeaders": ["Mcp-Session-Id"],
                }
            },
            "targets": [
                {
                    "name": "system",
                    "stdio": {
                        "cmd": controller_python,
                        "args": [str(repo / "services" / "controller" / "system_mcp_server.py")],
                        "env": {"ARES_SYSTEM_URL": "http://127.0.0.1:8788"},
                    },
                },
                {"name": "hermes", "stdio": {"cmd": hermes, "args": ["mcp", "serve"]}},
                {
                    "name": "jaeger",
                    "stdio": {
                        "cmd": controller_python,
                        "args": [str(repo / "services" / "controller" / "jaeger_mcp_proxy.py")],
                        "env": {
                            "JAEGER_BRIDGE_URL": "http://127.0.0.1:8791",
                        },
                    },
                },
            ],
        },
        "binds": [
            {
                "port": 8812,
                "listeners": [
                    {
                        "routes": [
                            {
                                "matches": [{"path": {"exact": "/.well-known/agent-card.json"}}],
                                "policies": {"a2a": {}},
                                "backends": [{"host": "127.0.0.1:8788"}],
                            },
                            {
                                "policies": {
                                    "apiKey": api_key_policy,
                                    "cors": {
                                        "allowOrigins": ["*"],
                                        "allowHeaders": ["content-type", "cache-control", "a2a-version"],
                                    },
                                    "a2a": {},
                                },
                                "backends": [{"host": "127.0.0.1:8788"}],
                            }
                        ]
                    }
                ],
            }
        ],
    }
    temporary = output.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
