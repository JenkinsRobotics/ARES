from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from core.automation import AutomationService
from core.automation.adapters import AdapterResult, AgentAdapter
from core.automation.store import AutomationStore
from fastapi_app.a2a_server import build_agent_card, select_agent
from fastapi_app.main import create_app


class _Adapter(AgentAdapter):
    def probe(self, _agent):
        return {"available": True}

    def start_run(self, _agent, _prompt, session_id, _emit, _cancel: threading.Event):
        return AdapterResult("done\nARES_STATUS: complete", session_id or "session-1")

    def cancel_run(self, _session_id):
        return None


def test_system_selector_is_explicit_and_defaults_to_hermes():
    assert select_agent("do the work") == ("hermes", "do the work")
    assert select_agent("@jaeger inspect this") == ("jaeger", "inspect this")
    assert select_agent("@openclaw inspect this") == ("openclaw", "inspect this")
    assert select_agent("Hermes: answer") == ("hermes", "answer")


def test_agent_card_declares_router_not_model_runtime():
    card = build_agent_card()
    assert card.name == "ARES System"
    assert "delegates" in card.description
    assert "@openclaw" in card.skills[0].description
    assert card.supported_interfaces[0].url.endswith("/a2a")


def test_agent_card_route_uses_official_a2a_sdk(tmp_path):
    service = AutomationService(
        store=AutomationStore(tmp_path / "state.json"),
        adapters={"hermes": _Adapter(), "jaeger": _Adapter()},
    )
    app = create_app(automation_service=service)
    with TestClient(app) as client:
        response = client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    assert response.json()["name"] == "ARES System"
    assert response.json()["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
    assert response.json()["supportedInterfaces"][0]["protocolVersion"] == "0.3"


def test_worker_card_and_integration_catalog_routes(tmp_path):
    service = AutomationService(
        store=AutomationStore(tmp_path / "state.json"),
        adapters={"hermes": _Adapter(), "jaeger": _Adapter()},
    )
    service.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "Independent worker", "model": "", "workspace": "/workspace",
    })
    app = create_app(automation_service=service)
    with TestClient(app) as client:
        worker = client.get("/api/agents/hermes/agent-card.json")
        catalog = client.get("/api/integrations")
    assert worker.status_code == 200
    assert worker.json()["runtimeOwner"] == "hermes"
    assert catalog.json()["network_gateway"] == "agentgateway"
