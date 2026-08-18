"""JaegerAI detection and default-election contract.

A stale ``ARES_JAEGER_HOME`` left over from the legacy JaegerAI checkout made a
perfectly good JaegerAI install report "not installed" — and the message told
the user to set the very variable that was already set and causing it. These
tests pin the diagnostic and the election rule that depends on it.
"""
from __future__ import annotations

import pytest

from api.providers.jaeger import paths, status


@pytest.fixture(autouse=True)
def _clear_status_cache():
    status.reset_cache()
    yield
    status.reset_cache()


def _fake_jaeger_root(tmp_path):
    """Build a tree that satisfies ``is_jaeger_ai_root``."""
    root = tmp_path / "JaegerAI"
    (root / "jaeger_ai").mkdir(parents=True)
    launcher = root / "jaeger"
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    return root


def _clear_jaeger_env(monkeypatch):
    for name in (
        paths.ARES_JAEGER_HOME_ENV,
        paths.JAEGER_HOME_ENV,
        paths.ARES_JAEGER_SOURCE_DIR_ENV,
        paths.ARES_JAEGER_INSTANCE_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


# ── root detection ───────────────────────────────────────────────────────────


def test_valid_checkout_is_recognized_as_a_jaeger_root(tmp_path):
    assert paths.is_jaeger_ai_root(_fake_jaeger_root(tmp_path))


def test_directory_without_launcher_is_not_a_root(tmp_path):
    root = tmp_path / "JaegerAI"
    (root / "jaeger_ai").mkdir(parents=True)
    assert not paths.is_jaeger_ai_root(root)


def test_explicit_home_override_selects_that_checkout(tmp_path, monkeypatch):
    root = _fake_jaeger_root(tmp_path)
    _clear_jaeger_env(monkeypatch)
    monkeypatch.setenv(paths.ARES_JAEGER_HOME_ENV, str(root))
    assert paths.jaeger_home() == root.resolve()


# ── the regression: stale override must explain itself ───────────────────────


def test_configured_root_override_reports_the_variable_in_use(tmp_path, monkeypatch):
    _clear_jaeger_env(monkeypatch)
    monkeypatch.setenv(paths.ARES_JAEGER_HOME_ENV, "/nope/JaegerAI")
    assert paths.configured_root_override() == (paths.ARES_JAEGER_HOME_ENV, "/nope/JaegerAI")


def test_configured_root_override_is_none_when_nothing_is_set(monkeypatch):
    _clear_jaeger_env(monkeypatch)
    assert paths.configured_root_override() is None


def test_stale_override_names_the_variable_instead_of_saying_not_installed(monkeypatch):
    """The old message told the user to set the variable that was breaking it."""
    _clear_jaeger_env(monkeypatch)
    monkeypatch.setenv(paths.ARES_JAEGER_HOME_ENV, "/Users/nobody/GitHub/JaegerAI")

    result = status.check_status(use_cache=False)

    assert not result.available
    assert paths.ARES_JAEGER_HOME_ENV in result.message
    assert "/Users/nobody/GitHub/JaegerAI" in result.message
    assert result.details.get("configured_by") == paths.ARES_JAEGER_HOME_ENV
    assert result.details.get("configured_root") == "/Users/nobody/GitHub/JaegerAI"


def test_valid_checkout_via_override_reports_connected_over_the_bridge(tmp_path, monkeypatch):
    """Bridge-only availability is success; no HTTP gateway required (ADR-0008)."""
    _clear_jaeger_env(monkeypatch)
    monkeypatch.setenv(paths.ARES_JAEGER_HOME_ENV, str(_fake_jaeger_root(tmp_path)))

    result = status.check_status(use_cache=False)

    assert result.available, result.message
    assert result.details.get("mode") == "bridge"


# ── default election ─────────────────────────────────────────────────────────


def test_explicit_election_always_wins(monkeypatch):
    from api import backend_selector

    monkeypatch.setattr(backend_selector, "is_jaeger_available", lambda: True)
    assert backend_selector.get_active_backend({"ares_backend": "jaeger_local"}) == "jaeger_local"


def test_jaeger_is_the_default_when_nothing_is_elected_and_it_is_ready(monkeypatch):
    from api import backend_selector

    monkeypatch.setattr(backend_selector, "is_jaeger_available", lambda: True)
    assert backend_selector.get_active_backend({}) == backend_selector.BACKEND_JAEGER


def test_no_default_is_invented_when_jaeger_is_unavailable(monkeypatch):
    """Falls back cleanly to the 'choose a provider' state, not a substitute."""
    from api import backend_selector

    monkeypatch.setattr(backend_selector, "is_jaeger_available", lambda: False)
    assert backend_selector.get_active_backend({}) == ""


def test_election_survives_a_failing_availability_probe(monkeypatch):
    from api import backend_selector

    def _boom():
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(backend_selector, "is_jaeger_available", _boom)
    assert backend_selector.get_active_backend({}) == ""


def test_session_backend_inherits_the_jaeger_default(monkeypatch):
    from types import SimpleNamespace

    from api import backend_selector

    monkeypatch.setattr(backend_selector, "is_jaeger_available", lambda: True)
    session = SimpleNamespace(ares_backend=None)
    assert backend_selector.get_session_backend(session, {}) == backend_selector.BACKEND_JAEGER
