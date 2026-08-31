from fastapi.testclient import TestClient
from starlette.requests import Request

from fastapi_app.errors import CoreApiError
from fastapi_app.main import create_app
from fastapi_app.request_context import _enforce_tailscale_identity


def request(host: str, *, login: str = "", client: str = "127.0.0.1") -> Request:
    headers = [(b"host", host.encode())]
    if login:
        headers.append((b"tailscale-user-login", login.encode()))
    return Request({
        "type": "http", "method": "GET", "path": "/", "headers": headers,
        "client": (client, 12345), "server": ("127.0.0.1", 8788), "scheme": "https",
    })


def test_localhost_keeps_local_owner_access(monkeypatch):
    monkeypatch.delenv("ARES_WEBUI_TAILSCALE_USERS", raising=False)
    _enforce_tailscale_identity(request("127.0.0.1:8788"))


def test_tailnet_requires_injected_allowlisted_identity(monkeypatch):
    monkeypatch.setenv("ARES_WEBUI_TAILSCALE_USERS", "owner@example.com")
    for bad in (request("mac.tail.ts.net:8444"), request("mac.tail.ts.net:8444", login="other@example.com")):
        try:
            _enforce_tailscale_identity(bad)
        except CoreApiError:
            pass
        else:
            raise AssertionError("unauthorized tailnet request was allowed")
    _enforce_tailscale_identity(request("mac.tail.ts.net:8444", login="OWNER@example.com"))


def test_tailscale_header_is_rejected_on_direct_local_url(monkeypatch):
    monkeypatch.setenv("ARES_WEBUI_TAILSCALE_USERS", "owner@example.com")
    try:
        _enforce_tailscale_identity(request("127.0.0.1:8788", login="owner@example.com"))
    except CoreApiError as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("spoofed direct identity header was allowed")


def test_tailnet_identity_is_enforced_at_application_boundary(monkeypatch):
    monkeypatch.setenv("ARES_WEBUI_TAILSCALE_USERS", "owner@example.com")
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/", headers={"host": "127.0.0.1:8788"}).status_code == 200
        denied = client.get("/", headers={"host": "mac.tail.ts.net:8444"})
        assert denied.status_code in {401, 403}


def test_allowlisted_tailnet_identity_reaches_frontend(monkeypatch):
    monkeypatch.setenv("ARES_WEBUI_TAILSCALE_USERS", "owner@example.com")
    monkeypatch.setattr("api.network_trust.raw_peer_is_trusted_proxy", lambda _request: True)
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/",
            headers={
                "host": "mac.tail.ts.net:8444",
                "tailscale-user-login": "OWNER@example.com",
            },
        )
    assert response.status_code == 200
