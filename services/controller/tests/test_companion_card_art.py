"""Card art crosses the bridge, never the filesystem boundary.

The Avatar tab draws the Companion's face. The image lives inside
JaegerAI's install, which ARES may not read (root AGENTS.md rule 1), so
the peer serves the bytes over its own versioned query and ARES projects
them as an image response.

Everything here is bridge-level fakes: no JaegerAI install, no bridge
process, so CI and a developer box exercise the same code.
"""

import base64

import pytest

from api.providers.jaeger import companion_control


def _contract(queries):
    return {"operations": {"queries": list(queries), "commands": []}}


def _fake_bridge(monkeypatch, *, queries, art):
    calls = []

    def query(name, args=None):
        calls.append((name, args))
        return art

    monkeypatch.setattr(
        "api.providers.jaeger.streaming.local_integration_contract",
        lambda: _contract(queries))
    monkeypatch.setattr(
        "api.providers.jaeger.streaming.query_local_companion", query)
    return calls


def test_card_is_fetched_through_the_bridge(monkeypatch):
    art = {"id": "clanker", "mime": "image/png", "bytes": 4,
           "filename": "card.png", "data": base64.b64encode(b"png!").decode()}
    calls = _fake_bridge(monkeypatch, queries=["character_card"], art=art)

    result = companion_control.companion_card("clanker")

    assert result["id"] == "clanker"
    assert result["mime"] == "image/png"
    assert base64.b64decode(result["data"]) == b"png!"
    assert calls == [("character_card", {"id": "clanker"})]


def test_no_character_id_asks_for_the_active_one(monkeypatch):
    art = {"id": "assistant", "mime": "image/png", "data": "eA=="}
    calls = _fake_bridge(monkeypatch, queries=["character_card"], art=art)

    assert companion_control.companion_card() is not None
    assert calls == [("character_card", {})]


def test_a_runtime_without_the_query_is_not_an_error(monkeypatch):
    """Capability negotiation, not version sniffing: an older runtime
    simply has no art to give, and the UI draws its own placeholder."""
    calls = _fake_bridge(monkeypatch, queries=["identity"], art={"data": "eA=="})

    assert companion_control.companion_card("clanker") is None
    assert calls == []          # the query is never attempted


@pytest.mark.parametrize("art", [None, {}, {"mime": "image/png"}, "nope"])
def test_missing_art_reads_as_none(monkeypatch, art):
    _fake_bridge(monkeypatch, queries=["character_card"], art=art)
    assert companion_control.companion_card("clanker") is None


def test_bridge_failure_surfaces_as_a_control_error(monkeypatch):
    monkeypatch.setattr(
        "api.providers.jaeger.streaming.local_integration_contract",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(companion_control.CompanionControlError):
        companion_control.companion_card("clanker")


# ── the HTTP projection ─────────────────────────────────────────────


def _card_route():
    from fastapi_app.routers import companion as router_module
    return router_module


def test_route_returns_image_bytes(monkeypatch):
    module = _card_route()
    monkeypatch.setattr(
        "api.providers.jaeger.companion_control.companion_card",
        lambda character_id=None: {
            "id": "clanker", "mime": "image/png", "bytes": 4,
            "filename": "card.png",
            "data": base64.b64encode(b"png!").decode(),
        })

    class _Identity:
        profile = "default"

    response = module.get_companion_card(_Identity(), "clanker")

    assert response.body == b"png!"
    assert response.media_type == "image/png"
    assert "card.png" in response.headers["content-disposition"]


def test_route_404s_when_there_is_no_art(monkeypatch):
    module = _card_route()
    monkeypatch.setattr(
        "api.providers.jaeger.companion_control.companion_card",
        lambda character_id=None: None)

    class _Identity:
        profile = "default"

    from fastapi_app.errors import CoreApiError

    with pytest.raises(CoreApiError) as excinfo:
        module.get_companion_card(_Identity(), None)
    assert excinfo.value.status_code == 404


def test_route_rejects_unreadable_art(monkeypatch):
    """A frame that is not valid base64 is the peer's bug, not a 500 with
    a stack trace for the operator to decode."""
    module = _card_route()
    monkeypatch.setattr(
        "api.providers.jaeger.companion_control.companion_card",
        lambda character_id=None: {
            "id": "x", "mime": "image/png", "bytes": 0,
            "filename": "card.png", "data": "!!!not-base64!!!",
        })

    class _Identity:
        profile = "default"

    from fastapi_app.errors import CoreApiError

    with pytest.raises(CoreApiError) as excinfo:
        module.get_companion_card(_Identity(), None)
    assert excinfo.value.status_code == 502
