import pytest
from fastapi.testclient import TestClient
from fastapi_app.main import create_app

@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)

def test_provider_health_endpoint(client):
    res = client.get("/api/providers/health")
    assert res.status_code == 200
    data = res.json()
    assert "providers" in data
    assert "healthy_count" in data
    assert "total_count" in data
    provider_ids = [p["id"] for p in data["providers"]]
    assert "ollama" in provider_ids or "jaeger_local" in provider_ids or "xai-oauth" in provider_ids

def test_provider_filtered_models_endpoint(client):
    res = client.get("/api/providers/models")
    assert res.status_code == 200
    data = res.json()
    assert "models" in data
    assert "healthy_providers" in data
