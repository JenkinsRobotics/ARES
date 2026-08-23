"""User-defined behavioral directives injected into every worker turn.

Directives are standing instructions the user sets once ("reply in the shortest
form", "no markdown unless I ask for code") that ARES prepends to the execution
prompt for every turn, on every worker. They are ARES's, not the worker's: the
file lives under ``ARES_HOME`` and is applied at the ARES/worker seam, so
switching runtimes does not change which rules are in force.

Scope is deliberately behavioral. A directive is a sentence in a prompt, so it
can shape *how a worker answers* — it cannot configure the worker. In
particular it cannot elect a model: the JaegerAI bridge protocol carries only
``{"op": "send", "text": ..., "session": ...}`` (``bridge_client.py:92``), with
no model field, so "use model X" written as a directive is a request the engine
is free to ignore rather than a setting ARES enforces. ``directives_summary()``
says so explicitly rather than letting the count imply more control than exists.

Storage is a separate ``directives.yaml`` rather than a key in ``config.yaml``
because this is the one file the user is expected to open and edit by hand.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DIRECTIVES_FILENAME = "directives.yaml"

# A prompt-budget ceiling. Directives are prepended to every turn, so an
# unbounded file would silently eat the context window the conversation needs.
MAX_DIRECTIVES = 50
MAX_DIRECTIVE_CHARS = 2000

BLOCK_HEADER = "[ARES directives — standing instructions from the user. Obey these in your response.]"
BLOCK_FOOTER = "[End ARES directives]"


def directives_path() -> Path:
    """Location of the user-editable directives file."""
    home = os.environ.get("ARES_HOME", "").strip()
    base = Path(home).expanduser() if home else Path.home() / ".ares"
    return base / DIRECTIVES_FILENAME


def _coerce_directives(raw: Any) -> list[str]:
    """Normalize the ``directives:`` value into clean, bounded strings."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, (str, int, float)):
            continue
        text = " ".join(str(item).split())
        if not text:
            continue
        cleaned.append(text[:MAX_DIRECTIVE_CHARS])
        if len(cleaned) >= MAX_DIRECTIVES:
            break
    return cleaned


def read_directives_file() -> dict[str, Any]:
    """Return the raw stored state, whether or not directives are enabled.

    Never raises: a malformed or unreadable file degrades to "no directives"
    rather than failing every chat turn, since this sits on the turn hot path.
    """
    path = directives_path()
    try:
        if not path.exists():
            return {"directives": [], "enabled": False, "exists": False}
    except OSError:
        logger.debug("Directives path probe failed", exc_info=True)
        return {"directives": [], "enabled": False, "exists": False}

    try:
        import yaml

        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Could not parse %s; ignoring directives", path, exc_info=True)
        return {"directives": [], "enabled": False, "exists": True, "error": "unparsable"}

    if not isinstance(parsed, dict):
        return {"directives": [], "enabled": False, "exists": True, "error": "unexpected_shape"}

    return {
        "directives": _coerce_directives(parsed.get("directives")),
        "enabled": bool(parsed.get("enabled", False)),
        "exists": True,
        "updated_at": parsed.get("updated_at"),
    }


def load_active_directives() -> list[str]:
    """Directives that should be injected right now (empty when disabled)."""
    state = read_directives_file()
    if not state.get("enabled"):
        return []
    return list(state.get("directives") or [])


def directives_block(directives: list[str]) -> str:
    """Render directives and active cognitive mode as a labeled prompt block, or ``""`` when there are none.

    The block is labeled so a worker can tell standing user rules apart from the
    turn's actual request, and so the user can recognize their own rules if a
    worker echoes the prompt back.
    """
    mode_line = ""
    try:
        from core.modes import get_mode_manager
        current_mode = get_mode_manager().state.current_mode.value.upper()
        mode_line = f"- Active Cognitive Mode: {current_mode}"
    except Exception:
        pass

    if not directives and not mode_line:
        return ""
    lines = [BLOCK_HEADER]
    if mode_line:
        lines.append(mode_line)
    lines.extend(f"- {directive}" for directive in directives)
    lines.append(BLOCK_FOOTER)
    return "\n".join(lines)


def apply_directives(prompt: str) -> str:
    """Prepend the active directives block to an execution prompt.

    Applied at the ARES/worker seam so both prompt shapes are covered: the
    context-wrapped prompt built for stateless workers, and the clean user turn
    handed to gateway workers that keep their own continuity.
    """
    try:
        block = directives_block(load_active_directives())
    except Exception:
        logger.warning("Directive injection failed; sending prompt unchanged", exc_info=True)
        return prompt
    if not block:
        return prompt
    return f"{block}\n\n{prompt}"


def save_directives(directives: Any, *, enabled: bool = True) -> dict[str, Any]:
    """Persist directives, returning the stored state."""
    import yaml

    cleaned = _coerce_directives(directives)
    payload = {
        "directives": cleaned,
        "enabled": bool(enabled),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = directives_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    os.replace(tmp, path)
    return payload


def directives_summary() -> dict[str, Any]:
    """Glass-box view: what is actually in force on the next turn."""
    state = read_directives_file()
    enabled = bool(state.get("enabled"))
    stored = list(state.get("directives") or [])
    return {
        "enabled": enabled,
        # Stored vs active differ when the file exists but is switched off, which
        # is exactly the case a user needs to see when rules "aren't working".
        "stored_count": len(stored),
        "active_count": len(stored) if enabled else 0,
        "path": str(directives_path()),
        "scope": "behavioral",
        "note": (
            "Directives shape how workers respond. They cannot elect a model: "
            "the JaegerAI bridge protocol carries no model field, so model "
            "choice is not enforced by ARES on that path."
        ),
    }
