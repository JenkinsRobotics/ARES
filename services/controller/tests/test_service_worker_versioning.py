"""Regression guard for the /sw.js version handler.

sw.js derives its cache name and its pre-cache URLs from __WEBUI_VERSION__.
Served as a plain static file the token stays literal, so the cache name is a
constant, no release can invalidate the shell cache, and a stale icon,
manifest, or offline shell outlives every upgrade.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fastapi_app.main import create_app


@pytest.fixture
def frontend_root(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    root.mkdir()
    (root / "index.html").write_text(
        '<link rel="icon" href="static/favicon-32.png?v=__WEBUI_VERSION__">',
        encoding="utf-8",
    )
    (root / "sw.js").write_text(
        "const CACHE_NAME = 'ares-shell-__WEBUI_VERSION__';\n"
        "const VQ = '?v=__WEBUI_VERSION__';\n",
        encoding="utf-8",
    )
    return root


def get(app, path: str) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path)

    return asyncio.run(run())


def test_service_worker_has_no_unsubstituted_tokens(frontend_root: Path):
    response = get(create_app(frontend_root=frontend_root), "/sw.js")

    assert response.status_code == 200
    assert "__WEBUI_VERSION__" not in response.text


def test_service_worker_cache_name_matches_shell_version(frontend_root: Path):
    app = create_app(frontend_root=frontend_root)

    shell = get(app, "/")
    worker = get(app, "/sw.js")

    # The page requests assets with ?v=<version>; the worker must build its
    # pre-cache keys from the same token or every cache lookup misses.
    version = shell.text.split("?v=")[1].split('"')[0]
    assert f"ares-shell-{version}" in worker.text
    assert f"?v={version}" in worker.text


def test_service_worker_script_is_not_cached(frontend_root: Path):
    response = get(create_app(frontend_root=frontend_root), "/sw.js")

    # A cached worker script cannot deliver a new cache version to clients.
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("application/javascript")
