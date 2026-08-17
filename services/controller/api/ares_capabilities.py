"""Capability negotiation for ARES execution backends.

Jaeger is authoritative for its runtime features. ARES translates that
versioned contract into stable UI affordances and fails closed if negotiation
is unavailable or incompatible. Static values remain only for legacy backends
that do not expose a discovery contract.
"""
from __future__ import annotations

import time
from typing import Any

from api.backend_catalog import JAEGER_BACKEND_ID
from api.backend_selector import VALID_BACKENDS, normalize_backend


UI_CAPABILITIES = (
    "cloud_provider_model_settings", "mcp_server_config", "messaging_gateway",
    "kanban", "delegate_task", "character_persona_editing", "voice_settings", "skills",
    "cookbook_model_serving", "deep_research", "model_compare", "caldav",
    "image_gallery", "image_editor", "visual_reports", "teacher_escalation",
    "pdf_forms", "youtube_ingest", "session_mutations",
)

_LEGACY_CAPABILITIES: dict[str, set[str]] = {
    "hermes_local": {
        "cloud_provider_model_settings", "mcp_server_config",
        "messaging_gateway", "kanban", "delegate_task", "voice_settings",
    },
}

_JAEGER_UI_FEATURES = {
    "cloud_provider_model_settings": "runtime_settings",
    "mcp_server_config": "mcp_server_config",
    "character_persona_editing": "character_persona_editing",
    "voice_settings": "voice_settings",
    "skills": "skills",
    "session_mutations": "sessions",
}

_CONTRACT_CACHE: dict[str, Any] = {"at": 0.0, "value": None, "error": None}
_CONTRACT_CACHE_SECONDS = 5.0


def reset_capability_contract_cache() -> None:
    _CONTRACT_CACHE.update({"at": 0.0, "value": None, "error": None})


def _jaeger_contract() -> tuple[dict[str, Any] | None, str | None]:
    now = time.monotonic()
    if now - float(_CONTRACT_CACHE["at"] or 0.0) < _CONTRACT_CACHE_SECONDS:
        return _CONTRACT_CACHE["value"], _CONTRACT_CACHE["error"]
    try:
        from api.providers.jaeger.gateway_streaming import local_integration_contract

        contract = local_integration_contract()
        error = None
    except Exception as exc:
        contract = None
        error = f"{type(exc).__name__}: {exc}"
    _CONTRACT_CACHE.update({"at": now, "value": contract, "error": error})
    return contract, error


def capability_contract_for_backend(backend: str) -> dict[str, Any]:
    """Return translated flags together with their source and runtime contract."""
    selected = normalize_backend(backend)
    if selected == JAEGER_BACKEND_ID:
        contract, error = _jaeger_contract()
        features = contract.get("features", {}) if isinstance(contract, dict) else {}
        flags = {
            ui_name: bool(
                isinstance(features.get(runtime_name), dict)
                and features[runtime_name].get("available") is True
            )
            for ui_name, runtime_name in _JAEGER_UI_FEATURES.items()
        }
        session_feature = features.get("sessions") if isinstance(features, dict) else None
        session_contract = (
            session_feature.get("contract") if isinstance(session_feature, dict) else None
        )
        session_operations = (
            session_contract.get("operations") if isinstance(session_contract, dict) else {}
        )
        flags["session_mutations"] = bool(
            int((session_contract or {}).get("version") or 0) >= 2
            and all(
                isinstance(session_operations.get(name), dict)
                and session_operations[name].get("available") is True
                for name in ("create", "rename", "clear", "delete", "archive")
            )
        )
        flags["messaging_gateway"] = False
        # ARES's controller MCP server currently exposes project/session tools,
        # not Kanban or delegation. Those tabs remain unavailable until Jaeger
        # explicitly advertises corresponding runtime features.
        flags["kanban"] = False
        flags["delegate_task"] = False
        return {
            "backend": selected,
            "source": "runtime" if contract else "unavailable",
            "negotiated": contract is not None,
            "error": error,
            "runtime_contract": contract,
            "capabilities": {name: bool(flags.get(name, False)) for name in UI_CAPABILITIES},
        }

    enabled = _LEGACY_CAPABILITIES.get(selected, set()) if selected in VALID_BACKENDS else set()
    return {
        "backend": selected,
        "source": "legacy_static" if selected else "unavailable",
        "negotiated": False,
        "error": None,
        "runtime_contract": None,
        "capabilities": {name: name in enabled for name in UI_CAPABILITIES},
    }


def capabilities_for_backend(backend: str) -> dict[str, bool]:
    """Return stable UI flags while preserving the existing API shape."""
    return capability_contract_for_backend(backend)["capabilities"]
