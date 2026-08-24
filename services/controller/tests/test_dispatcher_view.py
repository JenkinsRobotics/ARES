"""Dispatcher is a dedicated persistent-agent tab in the WebUI shell."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "apps" / "web" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_dispatcher_is_a_first_class_tab() -> None:
    index = _read("index.html")
    panels = _read("panels.js")
    styles = _read("style.css")
    i18n = _read("i18n.js")

    assert index.count('data-panel="dispatcher"') == 2
    assert 'id="mainDispatcher"' in index
    assert 'id="panelDispatcher"' in index
    assert 'id="dispatcherHud"' in index
    assert 'id="dispatcherInput"' in index
    assert 'id="dispatcherTimeline"' in index
    assert 'static/dispatcher.js' in index
    assert 'static/dispatcher.css' in index
    assert "dispatcher: 'tab_dispatcher'" in panels
    assert "'dispatcher'" in panels
    assert "main.main.showing-dispatcher > #mainDispatcher" in styles
    assert "tab_dispatcher: 'Dispatcher'" in i18n


def test_dispatcher_tokens_match_the_charcoal_canvas() -> None:
    css = _read("dispatcher.css")
    assert "--dispatcher-bg:#0D0E11" in css
    assert "--dispatcher-dot:#22242D" in css
    assert "--dispatcher-grid:24px" in css
    assert "radial-gradient" in css
    assert "backdrop-filter" in css


def test_dispatcher_binds_a_persistent_session() -> None:
    js = _read("dispatcher.js")
    assert "ares-dispatcher-session-id" in js
    assert "async function loadDispatcher" in js
    assert "async function sendDispatcher" in js
    assert "function ensureDispatcherSession" in js
    assert "Pinned:" in js
    assert "await send()" in js
    assert "/api/session/pin" in js


def test_dispatcher_is_not_advertised_on_the_desktop_spa() -> None:
    desktop = (ROOT / "apps" / "desktop" / "static" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "dispatcher" not in desktop.lower()
