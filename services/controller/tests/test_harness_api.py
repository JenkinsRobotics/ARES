import pytest
from fastapi.testclient import TestClient
from fastapi_app.main import create_app

@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)

def test_harness_verify_diff_endpoint_rejects_stub(client):
    diff = """--- a/src/app.tsx
+++ b/src/app.tsx
@@ -1,2 +1,3 @@
+const handleBranch = (id) => console.log("stub", id);
"""
    res = client.post(
        "/api/harness/verify-diff",
        json={"task_description": "Branch Wire", "diff_text": diff},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["passed"] is False
    assert data["violations_count"] == 1
    assert "NO_CONSOLE_LOG_STUB" in data["remediation_prompt"]

def test_harness_verify_diff_endpoint_passes_clean(client):
    diff = """--- a/src/app.tsx
+++ b/src/app.tsx
@@ -1,2 +1,3 @@
+const handleBranch = (id) => api.forkSession(id);
"""
    res = client.post(
        "/api/harness/verify-diff",
        json={"task_description": "Branch Wire", "diff_text": diff},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["passed"] is True
    assert data["violations_count"] == 0
    assert data["remediation_prompt"] is None

def test_harness_get_chat_parity_matrix(client):
    res = client.get("/api/harness/matrix/chat-parity")
    assert res.status_code == 200
    data = res.json()
    assert "matrix_id" in data
    assert len(data["items"]) >= 5
    assert data["items"][0]["status"] == "pending"

def test_harness_create_matrix_endpoint(client):
    res = client.post(
        "/api/harness/matrix/create",
        json={
            "task_description": "Custom Research Task",
            "items": [
                {"id": "c1", "title": "Check 1", "description": "Desc 1"},
                {"id": "c2", "title": "Check 2", "description": "Desc 2"},
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["task_description"] == "Custom Research Task"
    assert len(data["items"]) == 2
