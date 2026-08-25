"""`ares doctor` must say which frontend is actually production.

Field blocker #5. The repo carries two frontends:

  * ``apps/web/static``  — vanilla JS SPA, the value of
    ``frontend.DEFAULT_FRONTEND_ROOT``, the only one FastAPI ever mounts.
  * ``apps/web-react``   — built, typechecked and unit-tested by the
    frontend-and-ownership CI job, and referenced by NO Python in
    services/.

So CI asserts web-react is healthy while the server never serves a byte of
it. An operator editing web-react sees a green pipeline and no change in
the running UI, and doctor said nothing either way. These tests pin that
doctor names the production root and states web-react's status explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.doctor import frontend_ownership_report


def _repo(tmp_path: Path, *, react=False, react_dist=False, static=True) -> Path:
    if static:
        s = tmp_path / "apps" / "web" / "static"
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
    assert "apps/web/static" in text
    assert "pass:" in text


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


def test_real_repo_reports_web_static_as_production():
    """Against the actual checkout, not a fixture."""
    from fastapi_app import frontend

    repo_root = Path(frontend.__file__).resolve().parents[3]
    findings = frontend_ownership_report(repo_root)
    prod = [m for s, m, _ in findings if s == "pass" and "apps/web/static" in m]
    assert prod, f"doctor did not identify the real production root: {findings}"


# --- doctor must probe the port the server actually uses -------------------

def test_webui_port_defaults_to_the_canonical_8788(monkeypatch):
    """Doctor hardcoded 8787 while everything else in the repo uses 8788.

    The `ares` launcher exports ARES_WEBUI_PORT=8788, ctl.sh, start.sh,
    install.sh, http_security, streaming and the MCP server all say 8788 —
    and doctor probed 8787, so it reported "ARES WebUI server is not
    responding" against a perfectly healthy server, and printed a Tailscale
    URL on the wrong port too.
    """
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


def test_doctor_no_longer_hardcodes_8787():
    """Guard the regression at the source level — five sites had it."""
    from pathlib import Path

    import cli.doctor as d

    # Comments may legitimately mention 8787 to explain the history; what
    # must not survive is 8787 in executable code.
    code = [
        ln for ln in Path(d.__file__).read_text().splitlines()
        if not ln.lstrip().startswith("#")
    ]
    offenders = [ln for ln in code if "8787" in ln]
    assert not offenders, f"doctor still hardcodes 8787: {offenders}"
