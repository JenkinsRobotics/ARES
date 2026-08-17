from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_overlapping_runtime_surfaces_declare_capability_requirements():
    index = (ROOT / "apps/web/static/index.html").read_text(encoding="utf-8")
    assert index.count('data-panel="tasks" data-capability-domain="work_management" data-requires-capability="schedules"') == 2
    assert index.count('data-panel="kanban" data-requires-capability="kanban"') == 2
    assert index.count('data-panel="skills" data-requires-capability="skills"') == 2
    assert index.count('data-panel="content" data-capability-domain="knowledge_media" data-requires-any-capability=') == 2
    assert index.count('data-requires-capability="mcp_server_config"') == 1
    assert index.count('data-requires-capability="tool_inventory"') == 1
    assert index.count('data-requires-capability="messaging_gateway"') == 1
    assert index.count('data-requires-capability="caldav"') >= 2
    assert "openCalDav" in index


def test_capability_status_stays_visible_unless_user_enables_hide_setting():
    index = (ROOT / "apps/web/static/index.html").read_text(encoding="utf-8")
    panels = (ROOT / "apps/web/static/panels.js").read_text(encoding="utf-8")
    styles = (ROOT / "apps/web/static/style.css").read_text(encoding="utf-8")
    assert "content:['deep_research','youtube_ingest','pdf_forms','image_gallery','image_editor','visual_reports']" in panels
    assert "requiredCapabilities.some(capability=>capabilities[capability]===true)" in panels
    assert "window._hideUnavailableFeatures===true&&requiredCapabilities.length" in panels
    assert "settingsHideUnavailableFeatures" in index
    assert '"hide_unavailable_features": False' in (ROOT / "services/controller/api/config.py").read_text(encoding="utf-8")
    assert "runtime features marked unavailable" in panels
    assert "capability_negotiated===true" in panels
    assert "runtimeCapabilityBanner" in panels
    assert "html:not([data-ares-capabilities-ready]) [data-requires-capability]" not in styles
    assert ".capability-unavailable" in styles


def test_hide_unavailable_features_preference_defaults_visible_and_round_trips(
    monkeypatch, tmp_path
):
    import api.config as config

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)
    assert config.load_settings()["hide_unavailable_features"] is False
    assert config.save_settings({"hide_unavailable_features": True})[
        "hide_unavailable_features"
    ] is True
    assert config.load_settings()["hide_unavailable_features"] is True


def test_unimplemented_prototypes_are_not_advertised_or_loaded():
    index = (ROOT / "apps/web/static/index.html").read_text(encoding="utf-8")
    for prototype in (
        "model_comparison.js",
        "research_suite.js",
        "worktree_modal.js",
        "claude_features.js",
    ):
        assert prototype not in index


def test_legacy_hermes_plugin_surface_is_not_visible_or_queried():
    index = (ROOT / "apps/web/static/index.html").read_text(encoding="utf-8")
    panels = (ROOT / "apps/web/static/panels.js").read_text(encoding="utf-8")
    assert 'data-settings-section="plugins"' not in index
    assert "api('/api/plugins')" not in panels
