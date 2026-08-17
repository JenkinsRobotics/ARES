"""Workspace-scoped artifact reads, writes, and calculated inventory."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any


MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
ARTIFACT_DIRECTORY = "artifacts"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class ArtifactError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _workspace(session_id: str) -> Path:
    from api.file_operations import FileOperationError, workspace_for_session

    try:
        root, _session = workspace_for_session(session_id)
    except FileOperationError as exc:
        raise ArtifactError(str(exc), exc.status_code) from exc
    return root.resolve()


def read_workspace_bytes(
    session_id: str,
    relative_path: str,
    *,
    max_bytes: int = MAX_ARTIFACT_BYTES,
) -> bytes:
    from api.workspace import open_anchored_fd, safe_resolve_ws

    root = _workspace(session_id)
    target = safe_resolve_ws(root, relative_path)
    if not target.is_file():
        raise ArtifactError("File not found", 404)
    descriptor = open_anchored_fd(root, target, want_dir=False)
    with os.fdopen(descriptor, "rb", closefd=True) as source:
        content = source.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ArtifactError(f"File is larger than {max_bytes} bytes", 413)
    return content


def _safe_filename(filename: str) -> str:
    name = _SAFE_NAME.sub("-", Path(str(filename or "")).name).strip(".-")
    if not name:
        raise ArtifactError("Artifact filename is required")
    return name[:180]


def write_artifact(session_id: str, filename: str, content: bytes) -> dict[str, Any]:
    from api.workspace import make_anchored_dir, open_anchored_create_fd, safe_resolve_ws

    if len(content) > MAX_ARTIFACT_BYTES:
        raise ArtifactError(f"Artifact is larger than {MAX_ARTIFACT_BYTES} bytes", 413)
    root = _workspace(session_id)
    directory = safe_resolve_ws(root, ARTIFACT_DIRECTORY)
    if not directory.exists():
        make_anchored_dir(root, directory)
    clean = _safe_filename(filename)
    stem, suffix = Path(clean).stem, Path(clean).suffix
    target = directory / clean
    counter = 2
    while target.exists():
        target = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    descriptor = open_anchored_create_fd(root, target)
    with os.fdopen(descriptor, "wb", closefd=True) as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    return {
        "name": target.name,
        "path": target.relative_to(root).as_posix(),
        "size": len(content),
        "media_type": _media_type(target.suffix),
    }


def _media_type(suffix: str) -> str:
    return {
        ".gif": "image/gif",
        ".html": "text/html",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".json": "application/json",
        ".md": "text/markdown",
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }.get(suffix.lower(), "application/octet-stream")


def list_artifacts(session_id: str) -> dict[str, Any]:
    from api.workspace import safe_resolve_ws

    root = _workspace(session_id)
    directory = safe_resolve_ws(root, ARTIFACT_DIRECTORY)
    items = []
    if directory.is_dir():
        for path in sorted(directory.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            if not path.is_file() or path.is_symlink():
                continue
            stat = path.stat()
            items.append(
                {
                    "name": path.name,
                    "path": path.relative_to(root).as_posix(),
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "media_type": _media_type(path.suffix),
                }
            )
    return {"count": len(items), "items": items}


def health_probe() -> None:
    """The artifact store has no optional runtime dependency."""


__all__ = [
    "ArtifactError",
    "health_probe",
    "list_artifacts",
    "read_workspace_bytes",
    "write_artifact",
]
