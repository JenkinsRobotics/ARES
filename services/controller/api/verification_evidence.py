"""Read-only projection of recorded ARES/Jaeger runtime evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

from api.config import REPO_ROOT


DEFAULT_EVIDENCE_PATH = REPO_ROOT.parent.parent / "docs" / "verification" / "jaeger-five-promises-evidence.json"


def _git_head(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=path, text=True,
            capture_output=True, timeout=2, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def verification_evidence(path: Path | None = None) -> dict[str, Any]:
    source = path or Path(os.environ.get("ARES_VERIFICATION_EVIDENCE") or DEFAULT_EVIDENCE_PATH)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"available": False, "reason": "No runtime evidence has been recorded.", "source": str(source)}
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "reason": f"Evidence is unreadable: {type(exc).__name__}", "source": str(source)}
    if not isinstance(payload, dict) or not str(payload.get("schema") or "").startswith("ares-jaeger-five-promises/"):
        return {"available": False, "reason": "Evidence schema is unsupported.", "source": str(source)}

    recorded = payload.get("commits") if isinstance(payload.get("commits"), dict) else {}
    current_ares = _git_head(REPO_ROOT.parent.parent)
    jaeger_root = Path(os.environ.get("ARES_WEBUI_AGENT_DIR") or (REPO_ROOT.parent.parent.parent / "JaegerAI"))
    current_jaeger = _git_head(jaeger_root)
    current = {"ares": current_ares, "jaeger": current_jaeger}
    stale_components = [
        name for name in ("ares", "jaeger")
        if recorded.get(name) and current.get(name) and recorded.get(name) != current.get(name)
    ]
    promises = []
    for name, value in (payload.get("promises") or {}).items():
        if not isinstance(value, dict):
            continue
        promises.append({
            "id": str(name), "result": str(value.get("result") or "unknown"),
            "boundary": str(value.get("boundary") or "unspecified"),
            "expected": value.get("expected"), "actual": value.get("actual"),
        })
    return {
        "available": True,
        "schema": payload.get("schema"),
        "source": str(source),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "command": payload.get("command") or [],
        "configuration": payload.get("configuration") or {},
        "commits": {"recorded": recorded, "current": current},
        "dirty_worktrees": payload.get("dirty_worktrees") or {},
        "stale": bool(stale_components),
        "stale_components": stale_components,
        "promises": promises,
        "mocked_boundaries": payload.get("mocked_boundaries") or [],
        "untested_or_injected": payload.get("untested_or_injected") or [],
    }


__all__ = ["verification_evidence"]
