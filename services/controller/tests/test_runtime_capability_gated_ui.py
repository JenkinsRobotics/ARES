from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_overlapping_runtime_surfaces_declare_capability_requirements():
    index = (ROOT / "apps/web/static/index.html").read_text(encoding="utf-8")
    assert index.count('data-panel="tasks" data-capability-domain="work_management" data-requires-capability="schedules"') == 2
    assert index.count('data-panel="kanban" data-requires-capability="kanban"') == 2
    assert index.count('data-panel="skills" data-requires-capability="skills"') == 2
    assert index.count('data-requires-capability="mcp_server_config"') == 1
    assert index.count('data-requires-capability="tool_inventory"') == 1
    assert index.count('data-requires-capability="messaging_gateway"') == 1
    assert index.count('data-requires-capability="caldav"') >= 2
    assert "openCalDav" in index


def test_capability_gate_fails_closed_and_guards_programmatic_navigation():
    panels = (ROOT / "apps/web/static/panels.js").read_text(encoding="utf-8")
    styles = (ROOT / "apps/web/static/style.css").read_text(encoding="utf-8")
    assert "ARES_PANEL_CAPABILITIES={tasks:'schedules',kanban:'kanban',skills:'skills'}" in panels
    assert "capabilities[requiredCapability]!==true" in panels
    assert "gated UI remains unavailable" in panels
    assert "capability_negotiated===true" in panels
    assert "runtimeCapabilityBanner" in panels
    assert "html:not([data-ares-capabilities-ready]) [data-requires-capability]" in styles


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
