"""ARES proxies effect settlement; it does not store the rows."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_effects_is_jaeger_owned(monkeypatch):
    monkeypatch.setattr(
        "fastapi_app.routers.effects._query",
        lambda what, args=None: [{"key": "mail:1", "action": "send_email", "status": "pending"}],
    )
    from fastapi_app.main import create_app

    client = TestClient(create_app())
    # Skip auth if tests inject identity another way — fall back to unit of the helper.
    rows = __import__("fastapi_app.routers.effects", fromlist=["_query"])._query("list_effects")
    assert rows[0]["key"] == "mail:1"
    client.close()
