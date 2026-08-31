"""Resolve the JaegerAI product dependency without inspecting its state."""
from __future__ import annotations

import os
from pathlib import Path

ARES_JAEGER_HOME_ENV = "ARES_JAEGER_HOME"
JAEGER_HOME_ENV = "JAEGER_HOME"
ARES_JAEGER_SOURCE_DIR_ENV = "ARES_JAEGER_SOURCE_DIR"
ARES_JAEGER_INSTANCE_ENV = "ARES_JAEGER_INSTANCE"
ARES_NO_JAEGER_ENV = "ARES_NO_JAEGER"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def jaeger_integration_disabled() -> bool:
    """Return whether this process must skip all JaegerAI discovery."""
    return str(os.environ.get(ARES_NO_JAEGER_ENV, "")).strip().lower() in _TRUTHY


def expand_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def is_jaeger_ai_root(path: str | os.PathLike[str]) -> bool:
    """A current product root contains both the package and launcher."""
    try:
        root = expand_path(path)
        launcher = root / "jaeger"
        return (root / "jaeger_ai").is_dir() and launcher.is_file() and os.access(launcher, os.X_OK)
    except OSError:
        return False


def discover_jaeger_ai_source_root() -> Path | None:
    override = str(os.environ.get(ARES_JAEGER_SOURCE_DIR_ENV) or "").strip()
    if override:
        root = expand_path(override)
        return root if is_jaeger_ai_root(root) else None
    repository_root = Path(__file__).resolve().parents[3]
    for candidate in (repository_root.parent / "JaegerAI",):
        try:
            root = candidate.resolve()
        except OSError:
            continue
        if is_jaeger_ai_root(root):
            return root
    return None


def discover_jaeger_source_root() -> Path | None:
    return discover_jaeger_ai_source_root()


def jaeger_home() -> Path:
    raw = str(os.environ.get(ARES_JAEGER_HOME_ENV) or os.environ.get(JAEGER_HOME_ENV) or "").strip()
    if raw:
        return expand_path(raw)
    installed = expand_path("~/jaeger")
    if is_jaeger_ai_root(installed):
        return installed
    return discover_jaeger_ai_source_root() or installed


def jaeger_launcher() -> Path:
    return jaeger_home() / "jaeger"


def configured_root_override() -> tuple[str, str] | None:
    for name in (ARES_JAEGER_HOME_ENV, JAEGER_HOME_ENV):
        value = str(os.environ.get(name) or "").strip()
        if value:
            return name, value
    value = str(os.environ.get(ARES_JAEGER_SOURCE_DIR_ENV) or "").strip()
    return (ARES_JAEGER_SOURCE_DIR_ENV, value) if value else None


def jaeger_bridge_socket_candidates(
    home: str | os.PathLike[str] | None,
    instance: str | None,
) -> list[Path]:
    """Where a live ``jaeger bridge`` attach socket may be.

    Mirrors JaegerAI ``bridge_socket.candidate_paths`` without importing it.
    """
    name = str(instance or "").strip()
    if not name and home:
        active = expand_path(home) / ".jaeger_ai" / "active_instance"
        try:
            name = active.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    if not name:
        # Current JaegerAI installs own state under ~/.jaeger_ai. Keep the
        # historical ~/.jaeger candidate after it, but never spawn a second
        # bridge merely because ARES looked in the retired directory first.
        for state_name in (".jaeger_ai", ".jaeger"):
            active = Path.home() / state_name / "active_instance"
            try:
                name = active.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if name:
                break
    name = name or "default"
    out: list[Path] = []
    env_dir = str(os.environ.get("JAEGER_INSTANCE_DIR") or "").strip()
    if env_dir:
        out.append(expand_path(env_dir) / "run" / "bridge.sock")
    if home:
        root = expand_path(home)
        out.append(root / ".jaeger_ai" / "instances" / name / "run" / "bridge.sock")
    out.append(Path.home() / ".jaeger_ai" / "instances" / name / "run" / "bridge.sock")
    out.append(Path.home() / ".jaeger" / "instances" / name / "run" / "bridge.sock")
    seen: set[str] = set()
    unique: list[Path] = []
    for path in out:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def jaeger_instance_name() -> str | None:
    """Return only an explicit selector; Jaeger owns default resolution."""
    return str(os.environ.get(ARES_JAEGER_INSTANCE_ENV) or "").strip() or str(
        os.environ.get("JAEGER_INSTANCE_NAME") or ""
    ).strip() or None


def jaeger_update_repo() -> Path | None:
    """Resolve a checkout for read-only Git update metadata."""
    source = discover_jaeger_ai_source_root()
    if source is not None:
        return source
    home = jaeger_home()
    return home if (home / ".git").is_dir() else None


__all__ = [
    "ARES_JAEGER_HOME_ENV",
    "ARES_JAEGER_INSTANCE_ENV",
    "ARES_JAEGER_SOURCE_DIR_ENV",
    "ARES_NO_JAEGER_ENV",
    "JAEGER_HOME_ENV",
    "configured_root_override",
    "discover_jaeger_ai_source_root",
    "discover_jaeger_source_root",
    "expand_path",
    "is_jaeger_ai_root",
    "jaeger_bridge_socket_candidates",
    "jaeger_home",
    "jaeger_instance_name",
    "jaeger_integration_disabled",
    "jaeger_launcher",
    "jaeger_update_repo",
]
