#!/usr/bin/env python3
"""Install the machine-local, default-deny host capability grant registry."""

from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> int:
    state = Path(os.environ.get("ARES_HOME") or Path.home() / ".ares")
    output_dir = state / "capabilities"
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)
    workspace = Path.home() / "workspace"
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    common = [
        "capabilities.inspect", "workspace.list", "workspace.read", "workspace.write",
        "workspace.mkdir", "git.status", "git.diff", "service.status",
    ]
    document = {
        "version": 1,
        "identities": {
            "hermes": {"roots": [str(workspace)], "capabilities": common},
            "jaeger": {
                "roots": [str(workspace), str(Path.home() / "GitHub" / "JaegerAI")],
                "capabilities": common,
            },
            "admin": {
                "roots": [
                    str(workspace), str(Path.home() / "GitHub" / "ARES"),
                    str(Path.home() / "GitHub" / "JaegerAI"),
                ],
                "capabilities": common,
            },
        },
    }
    temporary = output_dir / "grants.json.tmp"
    output = output_dir / "grants.json"
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
