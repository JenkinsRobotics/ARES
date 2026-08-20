"""Unit tests for LSP/MCP-style contract and capability negotiation."""

from __future__ import annotations

import pytest

from api.contracts import (
    CURRENT_INTEGRATION_CONTRACT_VERSION,
    MIN_SUPPORTED_INTEGRATION_CONTRACT_VERSION,
    PROTOCOL_VERSION,
    has_capability,
    validate_contract_compatibility,
)
from api.providers.jaeger.bridge_client import JaegerClient, JaegerError


def test_contract_compatibility_allows_supported_ranges():
    """Verify that current (v7), backward-compatible (v6, v5), and forward (v8+) versions pass."""
    for version in [5, 6, 7, 8, 9, 10]:
        contract = {
            "contract": "ares-jaeger",
            "contract_version": version,
            "protocol_version": PROTOCOL_VERSION,
            "features": {"chat": {"available": True}},
        }
        valid, err = validate_contract_compatibility(contract)
        assert valid is True, f"Version {version} should be compatible, got error: {err}"
        assert err == ""


def test_contract_compatibility_rejects_breaking_legacy_versions():
    """Verify that unsupported legacy versions (< 5) and malformed payloads fail closed."""
    for legacy_version in [1, 2, 3, 4]:
        contract = {
            "contract": "ares-jaeger",
            "contract_version": legacy_version,
            "protocol_version": PROTOCOL_VERSION,
            "features": {},
        }
        valid, err = validate_contract_compatibility(contract)
        assert valid is False
        assert "incompatible ARES-Jaeger contract" in err
        assert f">= {MIN_SUPPORTED_INTEGRATION_CONTRACT_VERSION}" in err

    # Malformed contract identifier
    valid, err = validate_contract_compatibility({"contract": "invalid-engine"})
    assert valid is False
    assert "Unknown contract identifier" in err

    # Mismatched protocol version
    contract = {
        "contract": "ares-jaeger",
        "contract_version": CURRENT_INTEGRATION_CONTRACT_VERSION,
        "protocol_version": "999",
        "features": {},
    }
    valid, err = validate_contract_compatibility(contract)
    assert valid is False
    assert "disagrees with bridge protocol" in err


def test_has_capability_discovery():
    """Verify LSP/MCP-style feature discovery across features, domains, and operations."""
    contract = {
        "contract": "ares-jaeger",
        "contract_version": 7,
        "protocol_version": "1",
        "features": {
            "chat": {"available": True, "streaming": True},
            "voice": True,
            "disabled_feature": {"available": False},
        },
        "domains": {
            "agent_runtime": ["sessions", "approvals", "mcp"],
        },
        "operations": {
            "queries": ["contract", "character"],
            "commands": ["select_character", "create_session"],
        },
    }

    # Top-level feature tests
    assert has_capability(contract, "chat") is True
    assert has_capability(contract, "chat", "streaming") is True
    assert has_capability(contract, "chat", "non_existent_sub") is False
    assert has_capability(contract, "voice") is True
    assert has_capability(contract, "disabled_feature") is False

    # Domain feature tests
    assert has_capability(contract, "sessions") is True
    assert has_capability(contract, "mcp") is True
    assert has_capability(contract, "quantum_teleportation") is False

    # Operations feature tests
    assert has_capability(contract, "select_character") is True
    assert has_capability(contract, "create_session") is True
    assert has_capability(contract, "launch_missiles") is False


def test_bridge_client_uses_negotiated_contracts(monkeypatch):
    """Verify JaegerClient accepts backward and forward contract versions gracefully."""
    client = JaegerClient(command=["jaeger", "bridge"])

    # Test forward-compatible version 8 with extra additive metadata
    monkeypatch.setattr(client, "query", lambda _what: {
        "contract": "ares-jaeger",
        "contract_version": 8,
        "protocol_version": "1",
        "features": {"chat": {"available": True}},
        "future_field": "additive_data",
    })
    contract = client.integration_contract()
    assert contract["contract_version"] == 8
    assert contract["future_field"] == "additive_data"

    # Test legacy incompatible version fails closed
    monkeypatch.setattr(client, "query", lambda _what: {
        "contract": "ares-jaeger",
        "contract_version": 2,
        "protocol_version": "1",
        "features": {},
    })
    with pytest.raises(JaegerError, match="incompatible ARES-Jaeger contract"):
        client.integration_contract()
