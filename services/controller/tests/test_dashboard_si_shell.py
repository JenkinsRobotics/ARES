"""Contract for the chat-first SI HUD served from apps/dashboard/static."""

from pathlib import Path

from fastapi_app.frontend import DEFAULT_FRONTEND_ROOT


STATIC = Path(__file__).resolve().parents[1] / "apps" / "dashboard" / "static"

REQUIRED_IDS = (
    "system",
    "pause",
    "agents",
    "schematic",
    "systemMessage",
    "sendSystem",
    "systemAgent",
    "systemResult",
    "chatStream",
    "siName",
    "fleetStrip",
    "approvals",
    "goals",
    "runs",
    "integrations",
    "modelRoutes",
    "capacityMetrics",
    "specRuntime",
    "terminalStream",
)


def test_frontend_root_is_dashboard_static() -> None:
    assert DEFAULT_FRONTEND_ROOT.resolve() == STATIC.resolve()
    assert "apps/web/static" not in DEFAULT_FRONTEND_ROOT.as_posix()


def test_default_view_is_si_chat() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'class="si-shell"' in html
    assert 'id="chatStream"' in html
    assert 'id="systemDrawer"' in html
    assert 'src="/static/ares-console.js' in html
    assert 'src="/static/app.js' in html
    assert "__CSRF_TOKEN_JSON__" in html
    assert "One persistent SI" in html
    assert "Independent agents" not in html
    for element_id in REQUIRED_IDS:
        assert f'id="{element_id}"' in html, element_id


def test_send_uses_dispatch_turn_and_identity() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "/api/dispatch/turn" in script
    assert "conversation_id" in script
    assert "si_name" in script
    assert "owner_name" in script
    assert "/api/si/identity" in script
    assert "X-Ares-CSRF-Token" in script
    assert "X-CSRF-Token" in script
    assert "/api/dispatch/approve" in script
    assert "/api/dispatch/reject" in script
    assert "awaiting_approval" in script
    assert "Controller is not running" in script
    assert "launchd" in script


def test_console_keeps_csrf_header() -> None:
    script = (STATIC / "ares-console.js").read_text(encoding="utf-8")
    assert "X-Ares-CSRF-Token" in script
    assert "capacityMetrics" in script
    assert "schematic" in script
