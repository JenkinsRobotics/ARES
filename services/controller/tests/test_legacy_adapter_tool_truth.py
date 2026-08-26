"""The legacy adapter projection must not turn an unreadable inventory into none."""

from types import SimpleNamespace


class _Backend:
    def get_backend_name(self):
        return "Jaeger AI"

    def is_available(self):
        return True

    def health(self):
        return {"status": "ok"}

    def identity_projection(self):
        return {"name": "Jaeger AI"}

    def capabilities(self):
        return {}

    def chat_session_support(self):
        return {"streaming": True}

    def tools(self):
        return []

    def inventory(self):
        return {"active_execution": {"tools_unknown": True}}

    def settings_schema(self):
        return {"type": "object", "properties": {}}


def test_legacy_adapter_payload_preserves_unknown_tool_state(monkeypatch):
    from fastapi_app.routers import ares

    router = SimpleNamespace(list_all=lambda: {"jaeger_local": _Backend()})
    monkeypatch.setattr("api.backends.router.get_router", lambda: router)

    payload = ares.legacy_adapters(None)

    assert payload["jaeger_local"]["tools"] == []
    assert payload["jaeger_local"]["tools_unknown"] is True
