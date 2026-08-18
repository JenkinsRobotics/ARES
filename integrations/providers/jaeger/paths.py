"""Resolve the JaegerAI product dependency without inspecting its state."""
from __future__ import annotations

import os
from pathlib import Path

ARES_JAEGER_HOME_ENV = "ARES_JAEGER_HOME"
JAEGER_HOME_ENV = "JAEGER_HOME"
ARES_JAEGER_SOURCE_DIR_ENV = "ARES_JAEGER_SOURCE_DIR"
ARES_JAEGER_INSTANCE_ENV = "ARES_JAEGER_INSTANCE"


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
    "ARES_JAEGER_HOME_ENV", "ARES_JAEGER_INSTANCE_ENV", "ARES_JAEGER_SOURCE_DIR_ENV",
    "JAEGER_HOME_ENV", "configured_root_override", "discover_jaeger_ai_source_root",
    "discover_jaeger_source_root", "expand_path", "is_jaeger_ai_root", "jaeger_home",
    "jaeger_instance_name", "jaeger_launcher", "jaeger_update_repo",
]
