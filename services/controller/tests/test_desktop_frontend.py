"""Isolated /desktop SPA surface. The browser UI at / must stay untouched."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from fastapi_app.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
DESKTOP_STATIC = REPO_ROOT / "apps" / "desktop" / "static"


def _write_shell(root: Path, marker: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(
        (
            f"<!doctype html><title>{marker}</title>"
            f"<p>{marker}</p>"
            "<script>window.__ARES_CONFIG__="
            "{maxUploadBytes:__MAX_UPLOAD_BYTES__,csrfToken:__CSRF_TOKEN_JSON__};"
            "</script>"
            "<script>window.__ARES_WEBUI_BUNDLE_VERSION__='__WEBUI_VERSION__';</script>"
        ),
        encoding="utf-8",
    )
    (root / "style.css").write_text(f"/* {marker} css */\nbody{{margin:0}}\n", encoding="utf-8")
    return root


def _client(tmp_path: Path) -> TestClient:
    web = _write_shell(tmp_path / "web", "WEB_SHELL")
    desktop = _write_shell(tmp_path / "desktop", "DESKTOP_SHELL")
    return TestClient(create_app(frontend_root=web, desktop_root=desktop))


def test_desktop_shell_renders(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/desktop")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "DESKTOP_SHELL" in response.text
    assert "WEB_SHELL" not in response.text


def test_desktop_trailing_slash_and_static_asset(tmp_path: Path) -> None:
    client = _client(tmp_path)
    slash = client.get("/desktop/")
    assert slash.status_code == 200
    assert "DESKTOP_SHELL" in slash.text
    css = client.get("/desktop/style.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "DESKTOP_SHELL css" in css.text


def test_desktop_spa_fallback(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/desktop/workspace/untitled")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "DESKTOP_SHELL" in response.text


def test_desktop_token_substitution(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/desktop")
    assert "__WEBUI_VERSION__" not in response.text
    assert "__MAX_UPLOAD_BYTES__" not in response.text
    assert "__CSRF_TOKEN_JSON__" not in response.text
    assert "window.__ARES_WEBUI_BUNDLE_VERSION__=" in response.text
    assert "maxUploadBytes:" in response.text
    assert '"csrfToken"' in response.text


def test_web_root_is_unchanged_when_desktop_is_mounted(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "WEB_SHELL" in response.text
    assert "DESKTOP_SHELL" not in response.text


def test_unknown_api_paths_are_json_404_on_both_surfaces(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path in ("/api/definitely-not-a-route", "/desktop/api/definitely-not-a-route"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.headers["content-type"].startswith("application/json"), path
        assert response.json() == {"error": "not found"}, path
        assert "WEB_SHELL" not in response.text
        assert "DESKTOP_SHELL" not in response.text


def test_desktop_router_is_registered_before_web_catchall() -> None:
    app = create_app()
    paths: list[str] = []
    for route in app.router.routes:
        original = getattr(route, "original_router", None)
        if original is None:
            path = getattr(route, "path", "")
            if path:
                paths.append(str(path))
            continue
        paths.extend(str(getattr(inner, "path", "")) for inner in original.routes)
    desktop_idx = next(i for i, path in enumerate(paths) if path.startswith("/desktop"))
    catchall_idx = next(i for i, path in enumerate(paths) if path == "/{path:path}")
    assert desktop_idx < catchall_idx


def test_default_app_serves_the_shipped_desktop_shell() -> None:
    response = TestClient(create_app()).get("/desktop")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'data-pane="rail"' in response.text
    assert "__WEBUI_VERSION__" not in response.text


def test_shipped_desktop_shell_is_an_ide_layout() -> None:
    html = (DESKTOP_STATIC / "index.html").read_text(encoding="utf-8")
    css = (DESKTOP_STATIC / "style.css").read_text(encoding="utf-8")
    for pane in ("rail", "sidebar", "main", "bottom", "right"):
        assert f'data-pane="{pane}"' in html
    assert "display: grid" in css
    assert "resize: horizontal" in css
    assert "resize: vertical" in css
    assert "min-width: 1024px" in css
    assert "min-height: 700px" in css
    assert 'rel="manifest"' not in html
    assert "serviceWorker" not in html
    assert "navigator.serviceWorker" not in html
    assert not (DESKTOP_STATIC / "sw.js").exists()
    assert not (DESKTOP_STATIC / "manifest.json").exists()


def test_desktop_tree_has_no_retired_product_names() -> None:
    hits: list[str] = []
    for path in DESKTOP_STATIC.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "hermes" in text.lower():
            hits.append(str(path.relative_to(DESKTOP_STATIC)))
    assert hits == []
