from __future__ import annotations

from pathlib import Path

import pytest

from fastapi_app import lifecycle


CONTROLLER_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("host", ["127.0.0.1", "127.9.8.7", "localhost", "::1", "[::1]"])
def test_loopback_bind_does_not_require_authentication(monkeypatch, host):
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: False)
    lifecycle.enforce_authenticated_network_bind(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "100.64.0.10"])
def test_network_bind_requires_authentication(monkeypatch, host):
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: False)
    monkeypatch.delenv("ARES_WEBUI_ALLOW_UNAUTHENTICATED_NETWORK", raising=False)
    with pytest.raises(RuntimeError, match="Refusing to bind ARES"):
        lifecycle.enforce_authenticated_network_bind(host)


def test_authenticated_network_bind_is_allowed(monkeypatch):
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: True)
    lifecycle.enforce_authenticated_network_bind("0.0.0.0")


def test_insecure_network_override_is_explicit(monkeypatch, caplog):
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: False)
    monkeypatch.setenv("ARES_WEBUI_ALLOW_UNAUTHENTICATED_NETWORK", "true")
    lifecycle.enforce_authenticated_network_bind("0.0.0.0")
    assert "explicitly enabled" in caplog.text


def test_launchers_default_to_loopback():
    start = (CONTROLLER_ROOT / "start_ares.sh").read_text(encoding="utf-8")
    install = (CONTROLLER_ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    recovery = (CONTROLLER_ROOT / "scripts/enable_auto_recovery.sh").read_text(
        encoding="utf-8")
    assert 'ARES_WEBUI_HOST="${ARES_WEBUI_HOST:-127.0.0.1}"' in start
    assert 'HOST="${ARES_WEBUI_HOST:-127.0.0.1}"' in install
    assert "<key>ARES_WEBUI_HOST</key>" in recovery
    assert "<string>127.0.0.1</string>" in recovery
