from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "apps" / "web" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_overview_and_workbench_are_additive_tabs() -> None:
    index = _read("index.html")
    panels = _read("panels.js")

    assert index.count('data-panel="overview"') == 2
    assert index.count('data-panel="workbench"') == 2
    for marker in (
        'id="panelOverview"',
        'id="panelWorkbench"',
        'id="mainOverview"',
        'id="mainWorkbench"',
        'static/overview.js',
        'static/workbench.js',
        'static/ares_hubs.css',
    ):
        assert marker in index
    assert "'overview'" in panels
    assert "'workbench'" in panels
    assert "loadOverview" in panels
    assert "loadWorkbench" in panels
    assert "leaveOverview" in panels


def test_overview_projects_only_existing_public_contracts() -> None:
    source = _read("overview.js")
    for endpoint in (
        "/api/sessions",
        "/api/schedules",
        "/api/kanban/stats",
        "/api/approval/pending",
    ):
        assert endpoint in source
    assert "Promise.allSettled" in source
    assert "readFile" not in source
    assert "/jaeger/" not in source
    assert "owns no runtime state" in source


def test_workbench_reuses_current_surfaces_and_is_honest_about_missing_adapters() -> None:
    source = _read("workbench.js")
    for endpoint in (
        "/api/journal",
        "/api/model-intelligence",
        "/api/skills",
        "/api/extensions",
    ):
        assert endpoint in source
    for recovered_idea in (
        "Repository symbol map",
        "Theme Creator",
        "Typography packs",
        "Skin packs and branding",
        "MCP shortcuts",
    ):
        assert recovered_idea in source
    assert "Adapter needed" in source
    assert "No filesystem access is being guessed or bypassed" in source


def test_recovered_tabs_are_available_offline() -> None:
    service_worker = _read("sw.js")
    for asset in ("overview.js", "workbench.js", "ares_hubs.css"):
        assert f"'./static/{asset}' + VQ" in service_worker
