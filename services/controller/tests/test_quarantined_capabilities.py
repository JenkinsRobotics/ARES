from __future__ import annotations

from pathlib import Path

from fastapi_app.main import create_app


QUARANTINED_PATHS = {
    "/api/research/run",
    "/api/compare/run",
    "/api/research/youtube/extract",
    "/api/research/image/generate",
    "/api/research/teacher/evaluate",
    "/api/research/caldav/sync-event",
}


def _route_paths(app) -> set[str]:
    paths: set[str] = set()
    for included in app.routes:
        router = getattr(included, "original_router", None)
        routes = getattr(router, "routes", []) if router is not None else [included]
        paths.update(str(getattr(route, "path", "")) for route in routes)
    return paths


def test_synthetic_research_routes_are_not_registered():
    assert QUARANTINED_PATHS.isdisjoint(_route_paths(create_app()))


def test_research_suite_is_not_advertised_in_static_shell():
    root = Path(__file__).resolve().parents[3]
    index = (root / "apps" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-panel="research"' not in index
    assert "research_suite.js" not in index
