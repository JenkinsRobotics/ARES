"""Contract tests for ``GET /api/providers/health`` and ``/models``.

The health endpoint reports local Ollama only when the daemon at
127.0.0.1:11434 actually answers. The original version of this file
asserted ``"ollama" in provider_ids`` unconditionally, which made the
result depend on whether the developer happened to have Ollama running:
green on a workstation, red on CI, with nothing in the failure pointing
at the real cause.

It also built a ``~/.hermes/auth.json`` fixture and set ``HERMES_HOME``.
Nothing in the endpoint reads either — the setup was inert, so it looked
like the daemon branch was covered when it was not covered at all.

Both daemon states are now stubbed explicitly, so the suite pins the
actual behaviour and needs no live service.
"""

import pytest
from fastapi.testclient import TestClient
from fastapi_app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class _Answering:
    """Stand-in for a urlopen response from a healthy daemon."""

    status = 200

    def read(self):
        return b'{"models": []}'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def ollama_down(monkeypatch):
    """No local daemon — the CI machine's normal state."""
    import urllib.request

    def _refuse(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _refuse)


@pytest.fixture
def ollama_up(monkeypatch):
    """A local daemon that answers 200."""
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Answering())


def test_provider_health_endpoint_contract(client, ollama_down):
    """The response shape is what the web UI binds to, and it holds even
    when no provider is reachable at all."""
    res = client.get("/api/providers/health")
    assert res.status_code == 200
    data = res.json()
    assert "providers" in data
    assert "healthy_count" in data
    assert "total_count" in data
    assert data["total_count"] == len(data["providers"])
    assert data["healthy_count"] == sum(
        1 for p in data["providers"] if p["status"] == "healthy"
    )
    for provider in data["providers"]:
        assert {"id", "label", "status"} <= set(provider)


def test_ollama_is_reported_when_the_local_daemon_answers(client, ollama_up):
    res = client.get("/api/providers/health")
    assert res.status_code == 200
    entries = {p["id"]: p for p in res.json()["providers"]}
    assert "ollama" in entries, "a responding daemon must be reported"
    assert entries["ollama"]["status"] == "healthy"


def test_ollama_is_omitted_when_the_local_daemon_is_down(client, ollama_down):
    """The endpoint must not claim a provider that is not answering —
    reporting a dead daemon as available is worse than omitting it."""
    res = client.get("/api/providers/health")
    assert res.status_code == 200
    provider_ids = [p["id"] for p in res.json()["providers"]]
    assert "ollama" not in provider_ids


def test_healthy_providers_sort_ahead_of_unhealthy_ones(client, ollama_down):
    """The UI renders the list in order and expects usable providers first."""
    providers = client.get("/api/providers/health").json()["providers"]
    statuses = [p["status"] == "healthy" for p in providers]
    assert statuses == sorted(statuses, reverse=True)


def test_provider_filtered_models_endpoint(client, ollama_down):
    res = client.get("/api/providers/models")
    assert res.status_code == 200
    data = res.json()
    assert "models" in data
    assert "healthy_providers" in data
