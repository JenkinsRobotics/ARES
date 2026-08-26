#!/usr/bin/env python3
"""Fail closed when ARES's managed Hermes-fork metadata becomes dishonest."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream" / "hermes-webui.json"
OWNERSHIP = ROOT / "upstream" / "ownership.json"
REQUIRED_AREAS = {
    "apps/web/static",
    "services/controller",
    "apps/macos",
    "integrations",
    "core",
}


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=check,
        text=True,
        capture_output=True,
    )


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate(require_remote: bool) -> list[str]:
    errors: list[str] = []
    upstream = load(UPSTREAM)
    ownership = load(OWNERSHIP)

    for key in (
        "name",
        "url",
        "tracked_branch",
        "remote_name",
        "last_merged_upstream_commit",
        "ares_merge_commit",
        "license",
        "integration_model",
    ):
        if not upstream.get(key):
            errors.append(f"missing upstream field: {key}")

    if upstream.get("integration_model") != "managed-fork-overlay":
        errors.append("integration_model must remain managed-fork-overlay")

    for key in ("last_merged_upstream_commit", "ares_merge_commit"):
        revision = upstream.get(key, "")
        result = git("cat-file", "-e", f"{revision}^{{commit}}", check=False)
        if result.returncode:
            errors.append(f"{key} is not a commit available in this repository: {revision}")

    areas = ownership.get("areas", [])
    area_paths = {item.get("path") for item in areas}
    missing = REQUIRED_AREAS - area_paths
    if missing:
        errors.append("ownership metadata misses: " + ", ".join(sorted(missing)))

    allowed = set(ownership.get("allowed_classifications", []))
    for item in areas:
        path = item.get("path", "")
        if item.get("classification") not in allowed:
            errors.append(f"invalid classification for {path}")
        if not (ROOT / path).is_dir():
            errors.append(f"owned area does not exist: {path}")
        if not item.get("reason"):
            errors.append(f"owned area has no reason: {path}")

    remote_name = upstream.get("remote_name", "")
    remote = git("remote", "get-url", remote_name, check=False)
    if remote.returncode:
        if require_remote:
            errors.append(f"required git remote is missing: {remote_name}")
    elif remote.stdout.strip().removesuffix(".git") != upstream["url"].removesuffix(".git"):
        errors.append(
            f"remote {remote_name} points to {remote.stdout.strip()}, expected {upstream['url']}"
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-remote",
        action="store_true",
        help="also require the local hermes-upstream git remote",
    )
    args = parser.parse_args()
    errors = validate(args.require_remote)
    if errors:
        print("Upstream contract FAILED:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Upstream contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
