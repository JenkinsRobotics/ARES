"""Hermes vanilla-UI static-file serving for the FastAPI application.

This module intentionally owns no API routes. It is included after every API
router so the SPA fallback can never shadow a backend endpoint.

The Hermes WebUI is a vanilla JS/HTML/CSS single-page application. Static files
live in apps/web/static/ and are served under the /static/ URL prefix, matching
the original Hermes server's convention. The index.html uses template tokens
(__WEBUI_VERSION__, __MAX_UPLOAD_BYTES__, __CSRF_TOKEN_JSON__) that are
substituted at request time.
"""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response


DEFAULT_FRONTEND_ROOT = Path(__file__).resolve().parents[3] / "apps" / "web" / "static"

# Hermes template tokens (substituted in index.html at request time)
_WEBUI_VERSION_PLACEHOLDER = "__WEBUI_VERSION__"
_MAX_UPLOAD_PLACEHOLDER = "__MAX_UPLOAD_BYTES__"
_CSRF_TOKEN_PLACEHOLDER = "__CSRF_TOKEN_JSON__"

# Files served directly from the static root (not under /static/ prefix)
_FRONTEND_ROOT_FILES = {
    "manifest.json",
    "manifest.webmanifest",
    "sw.js",
    "share.html",
    "apple-touch-icon.png",
    "favicon-192.png",
    "favicon-32.png",
    "favicon-512.png",
    "favicon-512.svg",
    "favicon.ico",
    "favicon.svg",
    "robots.txt",
}
_FRONTEND_FILE_SUFFIXES = {
    ".css",
    ".gif",
    ".html",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".png",
    ".svg",
    ".txt",
    ".webmanifest",
    ".webp",
    ".woff",
    ".woff2",
}
_MANIFEST_ALIASES = {
    "manifest.json",
    "manifest.webmanifest",
    "session/manifest.json",
    "session/manifest.webmanifest",
}

CsrfTokenResolver = Callable[[Request], str]


def csrf_token_for_request(request: Request) -> str:
    """Resolve the current cookie session's CSRF token."""
    try:
        from api.auth import (
            _resolve_cookie_name,
            csrf_token_for_session,
            is_auth_enabled,
            verify_session,
        )

        if not is_auth_enabled():
            return ""
        cookie_value = request.cookies.get(_resolve_cookie_name())
        if cookie_value and verify_session(cookie_value):
            return csrf_token_for_session(cookie_value) or ""
    except Exception:
        pass
    return ""


def _json_not_found(message: str = "not found") -> JSONResponse:
    return JSONResponse({"error": message}, status_code=404)


def _is_api_path(path: str) -> bool:
    return path == "api" or path.startswith("api/")


def _is_static_asset(path: str) -> bool:
    """Check if path is a static file request (under /static/ prefix or root file)."""
    if _is_api_path(path):
        return False
    # Hermes references all JS/CSS/etc. under the static/ prefix
    if path.startswith("static/"):
        return True
    # Root-level files (manifest, favicon, sw.js, etc.)
    if path in _FRONTEND_ROOT_FILES:
        return True
    # Any file with a known suffix that's not under api/
    if Path(path).suffix.lower() in _FRONTEND_FILE_SUFFIXES:
        return True
    return False


def _strip_static_prefix(path: str) -> str:
    """Strip the leading 'static/' prefix so we can resolve the file in the root."""
    if path.startswith("static/"):
        return path[len("static/"):]
    return path


def _resolve_file(root: Path, relative_path: str) -> Path | None:
    root = root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".js":
        return "application/javascript"
    if suffix == ".webmanifest":
        return "application/manifest+json"
    if suffix == ".css":
        return "text/css"
    if suffix == ".html":
        return "text/html"
    if suffix == ".json":
        return "application/json"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _frontend_file(root: Path, path: str) -> Response:
    """Serve a static file, stripping the static/ prefix if present."""
    file_path = _strip_static_prefix(path)
    target = _resolve_file(root, file_path)
    if target is None:
        return _json_not_found()
    is_site_icon = "icon" in Path(path).name or Path(path).name.startswith("favicon")
    cache_control = (
        "no-store"
        if is_site_icon
        else "public, max-age=300"
    )
    return FileResponse(
        target,
        media_type=_media_type(target),
        headers={
            "Cache-Control": cache_control,
            "X-ARES-Frontend": "hermes",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _manifest(root: Path) -> Response:
    manifest = _resolve_file(root, "manifest.json")
    if manifest is None:
        return _json_not_found()
    return FileResponse(
        manifest,
        media_type="application/manifest+json",
        headers={
            "Cache-Control": "no-store",
            "X-ARES-Frontend": "hermes",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _spa_shell(root: Path, request: Request, resolve_csrf: CsrfTokenResolver) -> Response:
    """Serve index.html with Hermes template tokens substituted."""
    index_path = _resolve_file(root, "index.html")
    if index_path is None:
        return _json_not_found("Hermes frontend not found")
    try:
        html = index_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return HTMLResponse(
            "<!doctype html><title>ARES unavailable</title>"
            "<h1>Ares is restarting</h1><p>Please retry in a moment.</p>",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    # Resolve template values
    csrf_token = resolve_csrf(request)
    csrf_json = json.dumps({"csrfToken": csrf_token}, ensure_ascii=False).replace("<", "\\u003c")

    try:
        from api.updates import WEBUI_VERSION
        version = WEBUI_VERSION or "dev"
    except Exception:
        version = "dev"

    try:
        from api.config import MAX_UPLOAD_BYTES
        max_upload = str(MAX_UPLOAD_BYTES)
    except Exception:
        max_upload = "104857600"

    html = (
        html
        .replace(_WEBUI_VERSION_PLACEHOLDER, version)
        .replace(_MAX_UPLOAD_PLACEHOLDER, max_upload)
        .replace(_CSRF_TOKEN_PLACEHOLDER, csrf_json)
    )

    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "X-ARES-Frontend": "hermes",
        },
    )


def create_frontend_router(
    *,
    frontend_root: Path | None = None,
    csrf_resolver: CsrfTokenResolver | None = None,
) -> APIRouter:
    """Create the final catch-all router for the Hermes vanilla UI."""
    root = Path(frontend_root or DEFAULT_FRONTEND_ROOT)
    resolve_csrf = csrf_resolver or csrf_token_for_request
    router = APIRouter(include_in_schema=False)

    @router.api_route("/{path:path}", methods=["GET", "HEAD"])
    async def serve_frontend(request: Request, path: str) -> Response:
        clean_path = path.lstrip("/")

        # Unknown API routes must remain JSON 404s, never SPA HTML.
        if _is_api_path(clean_path):
            return _json_not_found()

        if clean_path in _MANIFEST_ALIASES:
            return _manifest(root)
        if _is_static_asset(clean_path):
            return _frontend_file(root, clean_path)
        # SPA fallback: serve index.html for all other paths
        return _spa_shell(root, request, resolve_csrf)

    return router
