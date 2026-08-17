import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

from api import runtime_credentials


def test_inventory_exposes_names_only(monkeypatch):
    monkeypatch.setattr(runtime_credentials, "_require_support", lambda: None)
    monkeypatch.setattr(
        "api.providers.jaeger.gateway_streaming.query_local_companion",
        lambda what, args: {"credentials": ["openai_api_key"], "count": 1},
    )
    assert runtime_credentials.list_runtime_credentials() == {"openai_api_key"}


def test_set_and_delete_are_bridge_commands(monkeypatch):
    monkeypatch.setattr(runtime_credentials, "_require_support", lambda: None)
    calls = []
    monkeypatch.setattr(
        "api.providers.jaeger.gateway_streaming.command_local_companion",
        lambda command, args: calls.append((command, args)) or {"ok": True},
    )
    runtime_credentials.set_runtime_credential("openai_api_key", "secret")
    runtime_credentials.delete_runtime_credential("openai_api_key")
    assert calls == [
        ("set_credential", {"name": "openai_api_key", "value": "secret"}),
        ("delete_credential", {"name": "openai_api_key"}),
    ]


def test_invalid_inventory_fails_closed(monkeypatch):
    monkeypatch.setattr(runtime_credentials, "_require_support", lambda: None)
    monkeypatch.setattr(
        "api.providers.jaeger.gateway_streaming.query_local_companion",
        lambda what, args: {"value": "must-not-be-returned"},
    )
    with pytest.raises(runtime_credentials.RuntimeCredentialError):
        runtime_credentials.list_runtime_credentials()


def test_compat_router_has_no_duplicate_native_mutation_routes():
    from fastapi_app.main import create_app

    app = create_app()
    expected_singletons = {
        ("POST", "/api/model/set"),
        ("POST", "/api/profile/switch"),
        ("POST", "/api/profile/create"),
        ("POST", "/api/profile/delete"),
        ("POST", "/api/session/new"),
        ("POST", "/api/transcribe"),
        ("POST", "/api/share/create"),
    }
    counts = {key: 0 for key in expected_singletons}
    for included in app.routes:
        router = getattr(included, "original_router", None)
        routes = getattr(router, "routes", []) if router is not None else [included]
        for route in routes:
            for method in getattr(route, "methods", set()):
                key = (method, getattr(route, "path", ""))
                if key in counts:
                    counts[key] += 1
    assert counts == {key: 1 for key in expected_singletons}


def _json_request(path: str, payload: bytes) -> Request:
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request({
        "type": "http",
        "method": "POST",
        "path": path,
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1),
    }, receive)


@pytest.mark.asyncio
async def test_compat_provider_mutations_delegate_to_runtime_service(monkeypatch):
    from fastapi_app.routers import hermes_compat

    calls = []
    monkeypatch.setattr(
        runtime_credentials,
        "set_runtime_credential",
        lambda name, value: calls.append(("set", name, value)) or {"ok": True},
    )
    monkeypatch.setattr(
        runtime_credentials,
        "delete_runtime_credential",
        lambda name: calls.append(("delete", name)) or {"ok": True},
    )

    saved = await hermes_compat.save_provider_key(
        _json_request(
            "/api/providers",
            b'{"provider":"anthropic","api_key":"test-secret"}',
        ),
        None,
    )
    deleted = await hermes_compat.delete_provider_key(
        _json_request(
            "/api/providers/delete", b'{"provider":"anthropic"}'),
        None,
    )

    assert saved == {"ok": True, "provider": "anthropic", "action": "saved"}
    assert deleted == {"ok": True, "provider": "anthropic", "action": "deleted"}
    assert calls == [
        ("set", "anthropic_api_key", "test-secret"),
        ("delete", "anthropic_api_key"),
    ]


@pytest.mark.asyncio
async def test_compat_provider_mutation_preserves_runtime_error_status(monkeypatch):
    from fastapi_app.routers import hermes_compat

    def unavailable(*_args):
        raise runtime_credentials.RuntimeCredentialError("runtime unavailable", 503)

    monkeypatch.setattr(runtime_credentials, "set_runtime_credential", unavailable)
    result = await hermes_compat.save_provider_key(
        _json_request(
            "/api/providers",
            b'{"provider":"anthropic","api_key":"test-secret"}',
        ),
        None,
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 503


@pytest.mark.asyncio
async def test_jaeger_provider_never_claims_ares_config_ownership(monkeypatch):
    from fastapi_app.routers import hermes_compat

    monkeypatch.setattr(hermes_compat, "_runtime_credential_names", lambda: set())
    monkeypatch.setattr(hermes_compat, "_jaeger_models", lambda: [])
    monkeypatch.setattr(hermes_compat, "_ollama_local_models", lambda: [])

    result = await hermes_compat.list_providers(None)
    jaeger = next(row for row in result["providers"] if row["id"] == "jaeger")
    assert jaeger["key_source"] == "jaeger_credential_store"
