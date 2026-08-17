"""Capability negotiation for ARES execution backends.

Jaeger is authoritative for its runtime features. ARES translates that
versioned contract into stable UI affordances and fails closed if negotiation
is unavailable or incompatible. Static values remain only for legacy backends
that do not expose a discovery contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import time
from typing import Any

from api.backend_catalog import JAEGER_BACKEND_ID
from api.backend_selector import VALID_BACKENDS, normalize_backend


@dataclass(frozen=True)
class FeatureSpec:
    """Stable UI name plus its negotiated runtime feature and local probe."""

    name: str
    description: str
    runtime_name: str | None = None
    local_probe: str | None = None
    invoke_probe: bool = False


FEATURE_REGISTRY = (
    FeatureSpec("chat", "Conversation execution and streaming."),
    FeatureSpec("approvals", "User approval requests for consequential actions."),
    FeatureSpec("cloud_provider_model_settings", "Runtime provider and model settings.", "runtime_settings"),
    FeatureSpec("mcp_server_config", "MCP server configuration."),
    FeatureSpec("tool_inventory", "Tools advertised by the selected runtime."),
    FeatureSpec("messaging_gateway", "Legacy external messaging gateway.", None),
    FeatureSpec("kanban", "Persistent work board.", "kanban", "api.kanban_bridge:_kb", True),
    FeatureSpec("delegate_task", "Task delegation.", "delegation", "api.delegation_runner:delegate"),
    FeatureSpec("schedules", "Time-based task execution.", "schedules", "api.schedules_store:ensure_schedule_runtime", True),
    FeatureSpec("character_persona_editing", "Assistant character and persona editing."),
    FeatureSpec("voice_settings", "Voice input and output settings."),
    FeatureSpec("skills", "Runtime skill discovery and management."),
    FeatureSpec("cookbook_model_serving", "Local model recipes and serving.", "cookbook_model_serving", "api.backends.ollama_hatchery:get_hatchery_status"),
    FeatureSpec("deep_research", "Iterative sourced research.", "deep_research", "api.research:health_probe", True),
    FeatureSpec("model_compare", "Compare responses from multiple models.", "model_compare", "api.model_intelligence:inventory"),
    FeatureSpec("caldav", "CalDAV calendar synchronization.", "caldav", "api.caldav_service:get_config"),
    FeatureSpec("image_gallery", "Generated image artifact gallery."),
    FeatureSpec("image_editor", "Image editing workflow."),
    FeatureSpec("visual_reports", "Generated visual reports."),
    FeatureSpec("teacher_escalation", "Escalate difficult turns to a stronger model.", "teacher_escalation", "api.model_intelligence:inventory"),
    FeatureSpec("pdf_forms", "PDF extraction and form filling."),
    FeatureSpec("youtube_ingest", "YouTube transcript ingestion."),
    FeatureSpec("session_mutations", "Versioned session mutation contract.", "sessions"),
)

UI_CAPABILITIES = tuple(feature.name for feature in FEATURE_REGISTRY)
FEATURES_BY_NAME = {feature.name: feature for feature in FEATURE_REGISTRY}

_LEGACY_CAPABILITIES: dict[str, set[str]] = {
    "hermes_local": {
        "cloud_provider_model_settings", "mcp_server_config",
        "messaging_gateway", "kanban", "delegate_task", "voice_settings",
    },
}

_JAEGER_UI_FEATURES = {
    feature.name: feature.runtime_name or feature.name
    for feature in FEATURE_REGISTRY
    if feature.name != "messaging_gateway"
}

_CONTRACT_CACHE: dict[str, Any] = {"at": 0.0, "value": None, "error": None}
_CONTRACT_CACHE_SECONDS = 5.0


def _ares_owned_feature_available(feature: str) -> bool:
    """Health-check ARES-owned halves of the negotiated integration.

    Jaeger advertises whether the combined product contract supports the
    feature. ARES still has to prove its local owner can load before exposing
    the UI; a contract claim alone must never turn a broken route into a tab.
    """
    spec = next(
        (item for item in FEATURE_REGISTRY if (item.runtime_name or item.name) == feature),
        None,
    )
    if spec is None or not spec.local_probe:
        return False
    try:
        module_name, attribute_name = spec.local_probe.split(":", 1)
        probe = getattr(import_module(module_name), attribute_name)
        if spec.invoke_probe:
            probe()
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
            "features": {
                feature.name: {
                    "description": feature.description,
                    "runtime_name": feature.runtime_name or feature.name,
                    "owner": ownership.get(feature.name, "none"),
                    "available": bool(flags.get(feature.name, False)),
                }
                for feature in FEATURE_REGISTRY
            },
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
        "features": {
            feature.name: {
                "description": feature.description,
                "runtime_name": feature.runtime_name or feature.name,
                "owner": "legacy" if feature.name in enabled else "none",
                "available": feature.name in enabled,
            }
            for feature in FEATURE_REGISTRY
        },
        "capabilities": {name: name in enabled for name in UI_CAPABILITIES},
    }


def capabilities_for_backend(backend: str) -> dict[str, bool]:
    """Return stable UI flags while preserving the existing API shape."""
    return capability_contract_for_backend(backend)["capabilities"]
