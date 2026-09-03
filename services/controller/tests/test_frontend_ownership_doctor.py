"""`ares doctor` must say which frontend is actually production.

Field blocker #5. FastAPI mounts ``services/controller/apps/dashboard/static``
(the value of ``frontend.DEFAULT_FRONTEND_ROOT``). ``apps/web/static`` and
``apps/web/dist`` are not production. ``apps/web-react`` may still exist as a
CI-tested tree that no Python in services/ serves.

So CI can assert web-react is healthy while the server never serves a byte of
it. These tests pin that doctor names the production root and states
web-react's status explicitly.
"""

from __future__ import annotations

from pathlib import Path

from cli.doctor import frontend_ownership_report


PRODUCTION = Path("services") / "controller" / "apps" / "dashboard" / "static"


def _repo(tmp_path: Path, *, react=False, react_dist=False, static=True) -> Path:
    if static:
        s = tmp_path / PRODUCTION
        s.mkdir(parents=True)
        (s / "index.html").write_text("<html></html>")
    if react:
        r = tmp_path / "apps" / "web-react"
        r.mkdir(parents=True)
        (r / "package.json").write_text("{}")
        if react_dist:
            (r / "dist").mkdir()
            (r / "dist" / "index.html").write_text("<html></html>")
    return tmp_path


def _joined(findings) -> str:
    return " | ".join(f"{s}:{m}" for s, m, _ in findings)


def test_names_the_production_root(tmp_path):
    text = _joined(frontend_ownership_report(_repo(tmp_path)))
    assert "services/controller/apps/dashboard/static" in text
    assert "pass:" in text
    assert "apps/web/static" not in text
    assert "apps/web/dist" not in text


def test_missing_production_root_is_a_failure(tmp_path):
    findings = frontend_ownership_report(_repo(tmp_path, static=False))
    assert any(s == "fail" for s, _, _ in findings), \
        "a missing production frontend must not pass silently"


def test_react_present_is_reported_as_not_production(tmp_path):
    findings = frontend_ownership_report(_repo(tmp_path, react=True))
    text = _joined(findings)
    assert "web-react" in text
    assert any(s == "warn" for s, _, _ in findings)
    assert "not" in text.lower() and "served" in text.lower()


def test_react_absent_produces_no_react_noise(tmp_path):
    """No second frontend, no warning — doctor must not invent problems."""
    findings = frontend_ownership_report(_repo(tmp_path))
    assert not any("web-react" in m for _, m, _ in findings)


def test_built_react_dist_is_called_out(tmp_path):
    """A built dist/ is the case where someone most likely believes it ships."""
    findings = frontend_ownership_report(_repo(tmp_path, react=True, react_dist=True))
    text = _joined(findings)
    assert "dist" in text
    assert any(s == "warn" for s, _, _ in findings)


def test_real_repo_reports_dashboard_static_as_production():
    """Against the actual checkout, not a fixture."""
    from fastapi_app import frontend

    repo_root = Path(frontend.__file__).resolve().parents[3]
    assert frontend.DEFAULT_FRONTEND_ROOT == repo_root / PRODUCTION
    findings = frontend_ownership_report(repo_root)
    prod = [
        m for s, m, _ in findings
        if s == "pass" and "services/controller/apps/dashboard/static" in m
    ]
    assert prod, f"doctor did not identify the real production root: {findings}"


# --- doctor must probe the port the server actually uses -------------------

def test_webui_port_defaults_to_the_canonical_8788(monkeypatch):
    """ARES WebUI is 8788. 8787 is the Hermes peer product, not the controller."""
    from cli.doctor import webui_port

    monkeypatch.delenv("ARES_WEBUI_PORT", raising=False)
    assert webui_port() == 8788


def test_webui_port_honours_the_launcher_override(monkeypatch):
    from cli.doctor import webui_port

    monkeypatch.setenv("ARES_WEBUI_PORT", "9999")
    assert webui_port() == 9999


def test_webui_port_falls_back_on_garbage(monkeypatch):
    from cli.doctor import webui_port

    monkeypatch.setenv("ARES_WEBUI_PORT", "not-a-port")
    assert webui_port() == 8788


def test_doctor_does_not_use_8787_as_the_webui_port():
    """Guard the controller-port regression; Hermes may still be named on 8787."""
    from cli.doctor import DEFAULT_WEBUI_PORT, PEER_PRODUCT_ENDPOINTS

    assert DEFAULT_WEBUI_PORT == 8788
    hermes = [url for name, _env, url in PEER_PRODUCT_ENDPOINTS if name == "Hermes"]
    assert hermes == ["http://127.0.0.1:8787"]
