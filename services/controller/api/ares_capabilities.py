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
    "chat", "approvals", "cloud_provider_model_settings", "mcp_server_config",
    "tool_inventory", "messaging_gateway", "kanban", "delegate_task", "schedules",
    "character_persona_editing", "voice_settings", "skills",
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
    "chat": "chat",
    "approvals": "approvals",
    "cloud_provider_model_settings": "runtime_settings",
    "mcp_server_config": "mcp_server_config",
    "tool_inventory": "tool_inventory",
    "kanban": "kanban",
    "delegate_task": "delegation",
    "schedules": "schedules",
    "character_persona_editing": "character_persona_editing",
    "voice_settings": "voice_settings",
    "skills": "skills",
    "session_mutations": "sessions",
    "cookbook_model_serving": "cookbook_model_serving",
    "deep_research": "deep_research",
    "model_compare": "model_compare",
    "caldav": "caldav",
    "image_gallery": "image_gallery",
    "image_editor": "image_editor",
    "visual_reports": "visual_reports",
    "teacher_escalation": "teacher_escalation",
    "pdf_forms": "pdf_forms",
    "youtube_ingest": "youtube_ingest",
}

_CONTRACT_CACHE: dict[str, Any] = {"at": 0.0, "value": None, "error": None}
_CONTRACT_CACHE_SECONDS = 5.0


def _ares_owned_feature_available(feature: str) -> bool:
    """Health-check ARES-owned halves of the negotiated integration.

    Jaeger advertises whether the combined product contract supports the
    feature. ARES still has to prove its local owner can load before exposing
    the UI; a contract claim alone must never turn a broken route into a tab.
    """
    try:
        if feature == "kanban":
            from api.kanban_bridge import _kb

            _kb()
            return True
        if feature == "delegation":
            from api.delegation_runner import delegate  # noqa: F401

            return True
        if feature == "schedules":
            from api.schedules_store import ensure_schedule_runtime

            ensure_schedule_runtime()
            return True
        if feature == "caldav":
            from api.caldav_service import get_config  # noqa: F401

            return True
        if feature in {"model_compare", "teacher_escalation"}:
            from api.model_intelligence import inventory  # noqa: F401

            return True
        if feature == "cookbook_model_serving":
            from api.backends.ollama_hatchery import get_hatchery_status  # noqa: F401

            return True
    except Exception:  # noqa: BLE001 - optional owner probes fail closed
        return False
    return False


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
        for ui_name, runtime_name in _JAEGER_UI_FEATURES.items():
            feature = features.get(runtime_name)
            if (
                flags.get(ui_name) is True
                and isinstance(feature, dict)
                and feature.get("owner") == "ares"
            ):
                flags[ui_name] = _ares_owned_feature_available(runtime_name)
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
        # The messaging gateway is a legacy Hermes transport and is not part
        # of the ARES-Jaeger contract. It remains unavailable unless a future
        # versioned contract gives it an explicit owner.
        flags["messaging_gateway"] = False
        ownership = {
            ui_name: str((features.get(runtime_name) or {}).get("owner") or "none")
            for ui_name, runtime_name in _JAEGER_UI_FEATURES.items()
            if isinstance(features.get(runtime_name), dict)
        }
        return {
            "backend": selected,
            "source": "runtime" if contract else "unavailable",
            "negotiated": contract is not None,
            "error": error,
            "runtime_contract": contract,
            "domains": contract.get("domains", {}) if isinstance(contract, dict) else {},
            "ownership": ownership,
            "capabilities": {name: bool(flags.get(name, False)) for name in UI_CAPABILITIES},
        }

    enabled = _LEGACY_CAPABILITIES.get(selected, set()) if selected in VALID_BACKENDS else set()
    return {
        "backend": selected,
        "source": "legacy_static" if selected else "unavailable",
        "negotiated": False,
        "error": None,
        "runtime_contract": None,
        "domains": {},
        "ownership": {},
        "capabilities": {name: name in enabled for name in UI_CAPABILITIES},
    }


def capabilities_for_backend(backend: str) -> dict[str, bool]:
    """Return stable UI flags while preserving the existing API shape."""
    return capability_contract_for_backend(backend)["capabilities"]
