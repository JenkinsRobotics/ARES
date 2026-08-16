import pytest
from fastapi.testclient import TestClient
from fastapi_app.main import create_app

@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)

def test_provider_health_endpoint(client, tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    auth_file = hermes_home / "auth.json"
    auth_file.write_text('{"credential_pool": {"ollama": [{"last_status": "ok"}]}}', encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    res = client.get("/api/providers/health")
    assert res.status_code == 200
    data = res.json()
    assert "providers" in data
    assert "healthy_count" in data
    assert "total_count" in data
    provider_ids = [p["id"] for p in data["providers"]]
    assert "ollama" in provider_ids

def test_provider_filtered_models_endpoint(client):
    res = client.get("/api/providers/models")
    assert res.status_code == 200
    data = res.json()
    assert "models" in data
    assert "healthy_providers" in data

