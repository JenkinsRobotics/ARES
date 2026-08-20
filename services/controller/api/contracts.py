"""Centralized contract definitions and semantic capability negotiation.

Adheres to LSP/MCP-style capability negotiation and Postel's robustness principle.
Rather than using brittle lockstep integer equality, clients and servers negotiate
capabilities via feature dictionaries and minimum supported version ranges.
"""

from __future__ import annotations

from typing import Any

# Minimum Jaeger integration contract version ARES supports
MIN_SUPPORTED_INTEGRATION_CONTRACT_VERSION = 5
CURRENT_INTEGRATION_CONTRACT_VERSION = 7

# Session contract versions
SESSION_CONTRACT_VERSION = 3
MIN_SUPPORTED_SESSION_CONTRACT_VERSION = 2

# Bridge protocol version
PROTOCOL_VERSION = "1"


def validate_contract_compatibility(
    contract: dict[str, Any] | None,
    min_version: int = MIN_SUPPORTED_INTEGRATION_CONTRACT_VERSION,
) -> tuple[bool, str]:
    """Validate integration contract compatibility using version ranges and schema checks.

    Returns (is_compatible, error_message).
    """
    if not isinstance(contract, dict):
        return False, "Jaeger bridge returned an invalid or empty integration contract"

    if contract.get("contract") != "ares-jaeger":
        return False, f"Unknown contract identifier: {contract.get('contract')!r}"

    version = contract.get("contract_version")
    if not isinstance(version, int) or version < min_version:
        return (
            False,
            f"incompatible ARES-Jaeger contract: expected >= {min_version}, received {version!r}",
        )

    protocol = str(contract.get("protocol_version") or "")
    if protocol != PROTOCOL_VERSION:
        return (
            False,
            f"Jaeger integration contract disagrees with bridge protocol (expected {PROTOCOL_VERSION}, got {protocol!r})",
        )

    return True, ""


def has_capability(
    contract: dict[str, Any] | None,
    feature_name: str,
    sub_feature: str | None = None,
) -> bool:
    """Check if the runtime contract exposes a specific capability (LSP/MCP style)."""
    if not isinstance(contract, dict):
        return False

    features = contract.get("features")
    if not isinstance(features, dict):
        features = {}

    # Check top-level features dict
    feat = features.get(feature_name)
    if isinstance(feat, dict):
        if sub_feature:
            return bool(feat.get(sub_feature))
        return feat.get("available", True) is True
    elif isinstance(feat, bool):
        return feat

    # Check domains
    domains = contract.get("domains")
    if isinstance(domains, dict):
        for _domain_name, domain_list in domains.items():
            if isinstance(domain_list, (list, tuple, set)) and feature_name in domain_list:
                return True

    # Check operations
    operations = contract.get("operations")
    if isinstance(operations, dict):
        for op_type in ("queries", "commands", "controls"):
            op_list = operations.get(op_type)
            if isinstance(op_list, (list, tuple, set)) and feature_name in op_list:
                return True

    return False
