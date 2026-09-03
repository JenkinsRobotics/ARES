"""Static contract for the ARES-owned Dispatcher projection.

The production UI FastAPI mounts is services/controller/apps/dashboard/static.
Dispatcher is a first-class SI agent surface in that shell. Hermes, Jaeger,
and OpenClaw stay external products, reached by loopback URL/port only.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "services" / "controller" / "apps" / "dashboard" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_dispatcher_is_a_first_class_current_ui_panel() -> None:
    index = _read("index.html")
    script = _read("app.js")

    assert 'data-agent="dispatcher"' in index
    assert 'id="dispatcherTier"' in index
    assert 'value="dispatcher"' in index
    assert "/api/dispatch/turn" in script
    assert 'src="/static/app.js' in index


def test_dispatcher_projects_current_ares_contracts() -> None:
    script = _read("app.js")
    index = _read("index.html")

    assert "/api/dispatch/turn" in script
    assert "/api/dispatch/approve" in script
    assert "/api/dispatch/reject" in script
    assert 'id="systemMessage"' in index
    assert 'id="sendSystem"' in index
    assert "si-shell" in index


def test_dispatcher_routes_through_ares_not_peer_product_code() -> None:
    """ARES owns product experience; peers are labeled by port, not imported."""
    index = _read("index.html")
    script = _read("app.js")

    assert 'data-service="hermes"' in index
    assert 'data-service="jaeger"' in index
    assert 'data-service="openclaw"' in index
    assert ":8787" in index
    assert ":8790" in index
    assert ":18789" in index
    assert "from jaeger" not in script.lower()
    assert "require(" not in script


def test_peer_products_are_endpoint_wired() -> None:
    index = _read("index.html")
    assert "Hermes" in index
    assert "Jaeger" in index
    assert "OpenClaw" in index
    assert ":8788" in index  # ARES controller


def test_dispatcher_assets_are_available_offline() -> None:
    assert (STATIC / "index.html").is_file()
    assert (STATIC / "app.js").is_file()
    assert (STATIC / "style.css").is_file()
