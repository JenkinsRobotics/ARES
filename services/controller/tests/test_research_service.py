"""Deep Research is importable, profile-scoped, and path safe."""

import asyncio

import pytest


def test_research_service_imports_from_controller_package():
    from api.research import DeepResearcher, ResearchHandler

    assert DeepResearcher is not None
    assert ResearchHandler is not None


def test_research_ids_cannot_escape_profile_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("api.profiles.get_active_ares_home", lambda: tmp_path)
    from api.research.handler import ResearchHandler

    handler = ResearchHandler()
    with pytest.raises(ValueError, match="session_id"):
        handler.get_result("../../outside")


def test_research_llm_uses_canonical_backend_router(tmp_path, monkeypatch):
    monkeypatch.setattr("api.profiles.get_active_ares_home", lambda: tmp_path)

    class Backend:
        def run_turn(self, message, session_id):
            assert message == "system\n\nprompt"
            assert session_id == "research:session-1"
            return {"text": "answer"}

    class Router:
        def select(self, backend_id):
            assert backend_id == "jaeger_local"
            return Backend()

    monkeypatch.setattr("api.backends.router.get_router", lambda: Router())
    monkeypatch.setattr("api.backend_selector.get_active_backend", lambda _config: "jaeger_local")
    monkeypatch.setattr("api.config.get_config", lambda: {})

    from api.research.handler import ResearchHandler

    call = ResearchHandler()._make_llm_callable("session-1")
    assert asyncio.run(call("prompt", "system")) == "answer"


def test_research_extraction_rejects_private_network_sources(monkeypatch):
    from api.research.search_bridge import _public_http_url

    monkeypatch.setattr(
        "api.research.search_bridge.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 80))],
    )
    with pytest.raises(ValueError, match="private or local"):
        _public_http_url("http://example.test/internal")
