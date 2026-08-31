#!/usr/bin/env python3
"""Install the machine-local, default-deny host capability grant registry."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

READ_CAPABILITIES = {
    "capabilities.inspect",
    "workspace.list",
    "workspace.read",
    "git.status",
    "git.diff",
    "service.status",
    "calendar.list",
    "notes.list",
    "notes.read",
    "reminders.list",
    "shortcuts.list",
    "camera.status",
}

# These capabilities are discoverable, but every invocation is still bound to
# an exact payload and a one-shot ARES approval lease by the host MCP server.
EFFECT_CAPABILITIES = {
    "workspace.write",
    "workspace.mkdir",
    "workspace.move",
    "calendar.create",
    "notes.create",
    "reminders.create",
    "shortcuts.run",
    "camera.snapshot",
    "camera.listen",
    "camera.ptz",
}


def _operator_policy(state: Path) -> dict:
    path = Path(
        os.environ.get("ARES_CAPABILITY_POLICY")
        or state / "config" / "host-capabilities.json"
    ).expanduser()
    if not path.exists():
        return {"version": 1, "identities": {}}
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 1 or not isinstance(document.get("identities"), dict):
        raise SystemExit(f"Unsupported host-capability policy: {path}")
    return document


def _additional_roots(policy: dict, identity: str) -> list[str]:
    entry = policy["identities"].get(identity) or {}
    if not isinstance(entry, dict) or not isinstance(entry.get("additional_roots", []), list):
        raise SystemExit(f"Malformed host-capability policy for identity: {identity}")
    roots: list[str] = []
    for raw in entry.get("additional_roots", []):
        root = Path(str(raw)).expanduser()
        if not root.is_absolute():
            raise SystemExit(f"Host-capability roots must be absolute: {raw}")
        roots.append(str(root.resolve()))
    return roots


def main() -> int:
    state = Path(os.environ.get("ARES_HOME") or Path.home() / ".ares")
    output_dir = state / "capabilities"
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)
    workspace = Path(os.environ.get("ARES_SHARED_WORKSPACE") or Path.home() / "workspace")
    workspace = workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    common = sorted(READ_CAPABILITIES | EFFECT_CAPABILITIES)
    output = output_dir / "grants.json"
    policy = _operator_policy(state)
    unknown = set(policy["identities"]) - {"hermes", "jaeger", "admin"}
    if unknown:
        raise SystemExit(f"Unknown host-capability identities: {', '.join(sorted(unknown))}")
    document = {"version": 1, "identities": {}}
    for identity in ("hermes", "jaeger", "admin"):
        document["identities"][identity] = {
            "roots": sorted({str(workspace), *_additional_roots(policy, identity)}),
            "capabilities": common,
        }
    if output.exists():
        previous = output.with_suffix(".json.previous")
        shutil.copy2(output, previous)
        previous.chmod(0o600)
    temporary = output_dir / "grants.json.tmp"
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
