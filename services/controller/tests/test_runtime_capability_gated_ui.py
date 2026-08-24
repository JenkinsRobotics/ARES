from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_overlapping_runtime_surfaces_declare_capability_requirements():
    """Every panel whose runtime can fail to serve it declares what it needs.

    Both nav surfaces (desktop rail + mobile bar) carry the declaration, hence
    a count of 2 per panel — a panel gated in one and not the other is the
    inconsistency this catches.

    The `content`, `modelLab` and CalDAV assertions this test used to make were
    removed with the surfaces themselves: `content` and `modelLab` are no
    longer panels, and the six tools behind the content capabilities
    (deep_research, youtube_ingest, pdf_forms, image_gallery, image_editor,
    visual_reports) were retired in 651c14433 along with the rest of the old
    ARES tool surface. Re-adding those declarations would advertise runtimes
    for panels that do not exist, which is the exact failure this file exists
    to prevent. Whether those panels should come back is a product question,
    not a test question — tracked in docs/architecture/phase0-stabilization.md.
    """
    index = (ROOT / "apps/web/static/index.html").read_text(encoding="utf-8")
    assert index.count('data-panel="tasks" data-capability-domain="work_management" data-requires-capability="schedules"') == 2
    assert index.count('data-panel="kanban" data-requires-capability="kanban"') == 2
    assert index.count('data-panel="skills" data-requires-capability="skills"') == 2


def test_no_panel_declares_a_capability_for_a_retired_tool():
    """The other direction: a declaration whose backend is gone is a lie.

    651c14433 retired the content tools. If a future change re-adds one of
    these declarations without re-adding the tool behind it, the UI is once
    again offering something the runtime cannot do.
    """
    index = (ROOT / "apps/web/static/index.html").read_text(encoding="utf-8")
    for capability in (
        "deep_research", "youtube_ingest", "pdf_forms",
        "image_gallery", "image_editor", "visual_reports",
    ):
        assert f'data-requires-capability="{capability}"' not in index, (
            f"{capability} is declared in the UI but its tool was retired in 651c14433"
        )


def test_capability_status_stays_visible_unless_user_enables_hide_setting():
    """An unavailable control is DIMMED, not deleted, unless the user opts in.

    A control that silently vanishes is indistinguishable from one that never
    existed, so the operator cannot tell "your runtime cannot do this" from
    "ARES cannot do this". Dimming keeps the cause explicable.

    The ``settingsHideUnavailableFeatures`` toggle assertion is dropped: the
    settings control was removed with the donor reinstall and re-adding it is
    UI work outside this phase. The PREFERENCE it drives still exists and still
    defaults to visible — asserted below and round-tripped by the next test —
    so the default behaviour is pinned even while the control is missing.
    """
    panels = (ROOT / "apps/web/static/panels.js").read_text(encoding="utf-8")
    styles = (ROOT / "apps/web/static/style.css").read_text(encoding="utf-8")
    config = (ROOT / "services/controller/api/config.py").read_text(encoding="utf-8")
    assert "requiredCapabilities.some(capability=>capabilities[capability]===true)" in panels
    assert "window._hideUnavailableFeatures===true&&requiredCapabilities.length" in panels
    assert '"hide_unavailable_features": False' in config
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
    i18n = (ROOT / "apps/web/static/i18n.js").read_text(encoding="utf-8")
    assert 'data-settings-section="plugins"' not in index
    assert "api('/api/plugins')" not in panels
    # English is the fallback locale. Other catalogs may still carry donor
    # strings; the operator-visible default must not.
    en_block = i18n.split("  en: {", 1)[1].split("\n  it: {", 1)[0]
    assert "View installed Hermes plugins" not in en_block
    assert "Hermes CLI/config" not in en_block
    # Product branding, not an untranslated technical term.
    assert "Hermes" not in i18n
