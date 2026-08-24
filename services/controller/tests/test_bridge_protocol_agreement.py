"""Swift, ARES, and JaegerAI must share one bridge protocol version.

ARES does not import ``jaeger_ai``. Agreement is pinned through the
checked-in ``protocol_v1_fixtures.json`` (the same file XCTest decodes)
and ``api.contracts.PROTOCOL_VERSION``. Extra capabilities on the wire
are additive: a client that does not implement ``streaming`` still
handshakes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.contracts import PROTOCOL_VERSION, has_capability


def _fixture_path() -> Path:
    explicit = Path(str(__import__("os").environ.get("JAEGER_OS_CONTRACT_FIXTURE") or ""))
    if explicit.is_file():
        return explicit
    sibling = Path(__file__).resolve().parents[3].parent / "JaegerAI" / (
        "packages/jaeger-os/jaeger_os/contract/protocol_v1_fixtures.json"
    )
    if sibling.is_file():
        return sibling
    pytest.skip("JaegerAI protocol fixtures not available")


def test_ares_protocol_version_matches_the_cross_language_fixture():
    data = json.loads(_fixture_path().read_text(encoding="utf-8"))
    assert data["proto"] == PROTOCOL_VERSION == "1"


def test_ready_capabilities_are_a_list_of_strings_and_include_the_v1_core():
    data = json.loads(_fixture_path().read_text(encoding="utf-8"))
    caps = data["frames"]["ready"]["capabilities"]
    assert isinstance(caps, list)
    assert caps, "ready.capabilities must not be empty"
    assert all(isinstance(item, str) and item for item in caps)
    required = {"query", "command", "chat", "sessions", "permissions", "agent_state"}
    assert required <= set(caps)


def test_streaming_is_additive_and_unknown_capabilities_are_not_required():
    data = json.loads(_fixture_path().read_text(encoding="utf-8"))
    caps = set(data["frames"]["ready"]["capabilities"])
    # A client may ignore streaming; it must not reject the handshake.
    contract = {
        "contract": "ares-jaeger",
        "contract_version": 7,
        "protocol_version": PROTOCOL_VERSION,
        "features": {name: {"available": True} for name in caps},
    }
    assert has_capability(contract, "chat") is True
    assert has_capability(contract, "quantum_teleportation") is False
    if "streaming" in caps:
        assert has_capability(contract, "streaming") is True


def test_delta_and_reasoning_frames_are_optional_on_the_wire():
    data = json.loads(_fixture_path().read_text(encoding="utf-8"))
    frames = data["frames"]
    for name in ("delta", "reasoning"):
        if name not in frames:
            continue
        assert frames[name]["type"] == name
        assert "text" in frames[name]
