"""Inventory is calculated from registrations instead of maintained counts."""

from fastapi import APIRouter
from fastapi.testclient import TestClient


def test_router_registry_has_unique_names_and_objects():
    from fastapi_app.routers import CORE_ROUTER_REGISTRY

    names = [entry.name for entry in CORE_ROUTER_REGISTRY]
    objects = [id(entry.router) for entry in CORE_ROUTER_REGISTRY]
    assert len(names) == len(set(names))
    assert len(objects) == len(set(objects))


def test_registered_routes_have_no_method_path_collisions():
    from fastapi_app.routers.inventory import _route_inventory

    assert _route_inventory()["duplicates"] == []


def test_route_count_tracks_router_content(monkeypatch):
    from fastapi_app.routers import CORE_ROUTER_REGISTRY, RouterRegistration
    from fastapi_app.routers import inventory as inventory_module

    extra = APIRouter(prefix="/api/inventory-test")

    @extra.get("")
    def inventory_test_route():
        return {"ok": True}

    before = inventory_module._route_inventory()["count"]
    monkeypatch.setattr(
        __import__("fastapi_app.routers", fromlist=["CORE_ROUTER_REGISTRY"]),
        "CORE_ROUTER_REGISTRY",
        (*CORE_ROUTER_REGISTRY, RouterRegistration("inventory_test", extra)),
    )
    assert inventory_module._route_inventory()["count"] == before + 1


def test_tool_count_tracks_tool_catalog(monkeypatch):
    from api import ares_tools
    from fastapi_app.routers.inventory import _tool_inventory

    before = _tool_inventory()["count"]
    monkeypatch.setattr(
        ares_tools,
        "ARES_TOOL_DEFS",
        [
            *ares_tools.ARES_TOOL_DEFS,
            {"name": "inventory_test", "description": "Test tool."},
        ],
    )
    assert _tool_inventory()["count"] == before + 1


def test_capability_catalog_is_one_to_one():
    from api.ares_capabilities import FEATURE_REGISTRY, UI_CAPABILITIES

    assert tuple(feature.name for feature in FEATURE_REGISTRY) == UI_CAPABILITIES
    assert len(UI_CAPABILITIES) == len(set(UI_CAPABILITIES))
    assert all(feature.description.strip() for feature in FEATURE_REGISTRY)


def test_inventory_endpoint_returns_calculated_state(monkeypatch):
    from fastapi_app.main import create_app
    from fastapi_app.request_context import RequestIdentity, require_identity
    from fastapi_app.routers import CORE_ROUTER_REGISTRY

    monkeypatch.setattr("api.backend_selector.get_active_backend", lambda _config: "jaeger_local")
    monkeypatch.setattr("api.skills_store.list_skills", lambda: {"skills": [{"name": "one"}]})
    monkeypatch.setattr("api.runtime_skills.selected_runtime_owns_skills", lambda: False)
    app = create_app()
    app.dependency_overrides[require_identity] = lambda: RequestIdentity(
        session_cookie=None,
        profile="default",
        auth_enabled=False,
    )
    response = TestClient(app).get("/api/inventory")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["generated"] is True
    assert payload["summary"]["routers"] == len(CORE_ROUTER_REGISTRY)
    assert payload["summary"]["routes"] == len(payload["routes"]["items"])
    assert payload["summary"]["skills"] == 1
    assert payload["routes"]["duplicates"] == []
