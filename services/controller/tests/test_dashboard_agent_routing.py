from pathlib import Path

STATIC = Path(__file__).parents[1] / "apps" / "dashboard" / "static"


def test_dashboard_offers_openclaw_and_data_driven_agent_routing():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'data-agent="openclaw"' in html
    assert "snapshot.agents.map(agent" in javascript
    assert "Route any registered @agent prefix" in javascript
    assert "agentDisplay(msg.agent)" in javascript
    assert "'/api/threads'" in javascript
    assert "/messages`" in javascript
    assert "window.localStorage.setItem('ares.activeThreadId'" in javascript


def test_inline_approval_survives_refresh_and_requires_informed_context():
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "item.run_id === row.run_id && item.status === 'pending'" in javascript
    assert "What you gain" in javascript
    assert "What could go wrong" in javascript
    assert "Exact scope" in javascript
    assert "Can it be undone?" in javascript
    assert "Safer option" in javascript
    assert "approvalInformed ? '' : 'disabled'" in javascript
