from fastapi.testclient import TestClient


def test_runtime_projection_is_bridge_owned(monkeypatch):
    from fastapi_app.main import create_app
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: False)
    monkeypatch.setattr(
        "fastapi_app.routers.jaeger_runtime._query",
        lambda what, args=None: [{"id": "c1"}] if what == "list_commitments" else [{"id": "r1", "state": "waiting_for_event", "wake_key": "pr:1"}],
    )
    with TestClient(create_app()) as client:
        response = client.get("/api/jaeger-runtime")
    assert response.status_code == 200
    assert response.json()["owner"] == "jaeger"
    assert response.json()["runs"][0]["wake_key"] == "pr:1"


def test_deliver_event_uses_bridge_command(monkeypatch):
    from fastapi_app.main import create_app
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: False)
    calls = []
    monkeypatch.setattr("fastapi_app.routers.jaeger_runtime._command", lambda cmd, args: calls.append((cmd, args)) or True)
    with TestClient(create_app()) as client:
        response = client.post("/api/jaeger-runtime/deliver-event", json={"wake_key": "pr:1"})
    assert response.status_code == 200
    assert calls == [("deliver_event", {"wake_key": "pr:1"})]
