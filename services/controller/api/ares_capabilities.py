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
    """Stable product capability and the component that owns its truth."""

    name: str
    description: str
    domain: str
    owner: str = "runtime"
    runtime_name: str | None = None
    local_probe: str | None = None
    invoke_probe: bool = False


FEATURE_REGISTRY = (
    FeatureSpec("chat", "Conversation execution and streaming.", "agent_runtime"),
    FeatureSpec("approvals", "User approval requests for consequential actions.", "agent_runtime"),
    FeatureSpec("cloud_provider_model_settings", "Runtime provider and model settings.", "agent_runtime", runtime_name="runtime_settings"),
    FeatureSpec("mcp_server_config", "MCP server configuration.", "extensibility"),
    FeatureSpec("tool_inventory", "Tools advertised by the selected runtime.", "extensibility"),
    FeatureSpec("messaging_gateway", "Legacy external messaging gateway.", "agent_runtime", owner="none"),
    FeatureSpec("kanban", "Persistent work board.", "work_management", "ares", "kanban", "api.kanban_bridge:_kb", True),
    FeatureSpec("delegate_task", "Task delegation.", "work_management", "ares", "delegation", "api.delegation_runner:delegate"),
    FeatureSpec("schedules", "Time-based task execution.", "work_management", "ares", "schedules", "api.schedules_store:ensure_schedule_runtime", True),
    FeatureSpec("character_persona_editing", "Assistant character and persona editing.", "agent_runtime"),
    FeatureSpec("voice_settings", "Voice input and output settings.", "agent_runtime"),
    FeatureSpec("skills", "Runtime skill discovery and management.", "extensibility"),
    FeatureSpec("cookbook_model_serving", "Local model recipes and serving.", "model_intelligence", "ares", "cookbook_model_serving", "api.backends.ollama_hatchery:get_hatchery_status"),
    FeatureSpec("deep_research", "Iterative sourced research.", "research", "ares", "deep_research", "api.research:health_probe", True),
    FeatureSpec("model_compare", "Compare responses from multiple models.", "research", "ares", "model_compare", "api.model_intelligence:inventory"),
    FeatureSpec("caldav", "CalDAV calendar synchronization.", "work_management", "ares", "caldav", "api.caldav_service:get_config"),
    FeatureSpec("image_gallery", "Generated image artifact gallery.", "creative_output", "ares", "image_gallery", "api.workspace_artifacts:health_probe", True),
    FeatureSpec("image_editor", "Image editing workflow.", "creative_output", "ares", "image_editor", "api.generated_artifacts:image_editor_health_probe", True),
    FeatureSpec("visual_reports", "Generated visual reports.", "creative_output", "ares", "visual_reports", "api.workspace_artifacts:health_probe", True),
    FeatureSpec("teacher_escalation", "Escalate difficult turns to a stronger model.", "research", "ares", "teacher_escalation", "api.model_intelligence:inventory"),
    FeatureSpec("pdf_forms", "PDF extraction and form filling.", "knowledge_media", "ares", "pdf_forms", "api.ingestion:pdf_health_probe", True),
    FeatureSpec("youtube_ingest", "YouTube transcript ingestion.", "knowledge_media", "ares", "youtube_ingest", "api.ingestion:youtube_health_probe", True),
    FeatureSpec("session_mutations", "Versioned session mutation contract.", "agent_runtime", runtime_name="sessions"),
)

UI_CAPABILITIES = tuple(feature.name for feature in FEATURE_REGISTRY)
FEATURES_BY_NAME = {feature.name: feature for feature in FEATURE_REGISTRY}

_LEGACY_CAPABILITIES: dict[str, set[str]] = {}

_JAEGER_UI_FEATURES = {
    feature.name: feature.runtime_name or feature.name
    for feature in FEATURE_REGISTRY
    if feature.owner == "runtime"
}


def _feature_domains() -> dict[str, list[str]]:
    domains: dict[str, list[str]] = {}
    for feature in FEATURE_REGISTRY:
        domains.setdefault(feature.domain, []).append(feature.name)
    return domains

_CONTRACT_CACHE: dict[str, Any] = {"at": 0.0, "value": None, "error": None}
_CONTRACT_CACHE_SECONDS = 5.0


def _ares_owned_feature_health(feature: str) -> tuple[bool, str | None]:
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
        return False, "ARES has no registered health probe for this feature"
    try:
        module_name, attribute_name = spec.local_probe.split(":", 1)
        probe = getattr(import_module(module_name), attribute_name)
        if spec.invoke_probe:
            probe()
        return True, None
    except Exception as exc:  # noqa: BLE001 - optional owner probes fail closed
        return False, f"{type(exc).__name__}: {exc}"


def reset_capability_contract_cache() -> None:
    _CONTRACT_CACHE.update({"at": 0.0, "value": None, "error": None})


def _jaeger_contract() -> tuple[dict[str, Any] | None, str | None]:
    now = time.monotonic()
    if now - float(_CONTRACT_CACHE["at"] or 0.0) < _CONTRACT_CACHE_SECONDS:
        return _CONTRACT_CACHE["value"], _CONTRACT_CACHE["error"]
    try:
        from api.providers.jaeger.streaming import local_integration_contract

        contract = local_integration_contract()
        error = None
    except Exception as exc:
        contract = None
        error = f"{type(exc).__name__}: {exc}"
    _CONTRACT_CACHE.update({"at": now, "value": contract, "error": error})
    return contract, error


def capability_contract_for_backend(backend: str) -> dict[str, Any]:
    """Compose ARES-local truth with the selected runtime's advertised truth."""
    selected = normalize_backend(backend)
    if selected == JAEGER_BACKEND_ID:
        contract, error = _jaeger_contract()
        features = contract.get("features", {}) if isinstance(contract, dict) else {}
        flags: dict[str, bool] = {
            ui_name: bool(
                isinstance(features.get(runtime_name), dict)
                and features[runtime_name].get("available") is True
            )
            for ui_name, runtime_name in _JAEGER_UI_FEATURES.items()
        }
        reasons: dict[str, str] = {}
        ownership = {
            ui_name: str((features.get(runtime_name) or {}).get("owner") or "runtime")
            for ui_name, runtime_name in _JAEGER_UI_FEATURES.items()
            if isinstance(features.get(runtime_name), dict)
        }
        for spec in FEATURE_REGISTRY:
            if spec.owner != "ares":
                continue
            available, reason = _ares_owned_feature_health(spec.runtime_name or spec.name)
            flags[spec.name] = available
            ownership[spec.name] = "ares"
            if reason:
                reasons[spec.name] = reason
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
        # The messaging gateway is a retired transport and is not part
        # of the ARES-Jaeger contract. It remains unavailable unless a future
        # versioned contract gives it an explicit owner.
        flags["messaging_gateway"] = False
        ownership["messaging_gateway"] = "none"
        return {
            "backend": selected,
            "source": "runtime" if contract else "unavailable",
            "negotiated": contract is not None,
            "error": error,
            "runtime_contract": contract,
            "domains": _feature_domains(),
            "ownership": ownership,
            "features": {
                feature.name: {
                    "description": feature.description,
                    "runtime_name": feature.runtime_name or feature.name,
                    "domain": feature.domain,
                    "owner": ownership.get(feature.name, feature.owner),
                    "available": bool(flags.get(feature.name, False)),
                    "status": "available" if flags.get(feature.name, False) else "unavailable",
                    "reason": reasons.get(feature.name)
                    or str(
                        (
                            features.get(feature.runtime_name or feature.name) or {}
                        ).get("reason")
                        or (
                            features.get(feature.runtime_name or feature.name) or {}
                        ).get("error")
                        or (error if feature.owner == "runtime" else "")
                        or ""
                    ),
                }
                for feature in FEATURE_REGISTRY
            },
            "capabilities": {name: bool(flags.get(name, False)) for name in UI_CAPABILITIES},
        }

    enabled = set(_LEGACY_CAPABILITIES.get(selected, set())) if selected in VALID_BACKENDS else set()
    local_reasons: dict[str, str] = {}
    for feature in FEATURE_REGISTRY:
        if feature.owner != "ares":
            continue
        available, reason = _ares_owned_feature_health(feature.runtime_name or feature.name)
        if available:
            enabled.add(feature.name)
        elif reason:
            local_reasons[feature.name] = reason
    return {
        "backend": selected,
        "source": "legacy_static" if selected else "unavailable",
        "negotiated": False,
        "error": None,
        "runtime_contract": None,
        "domains": _feature_domains(),
        "ownership": {
            feature.name: feature.owner
            for feature in FEATURE_REGISTRY
            if feature.owner != "runtime" or feature.name in enabled
        },
        "features": {
            feature.name: {
                "description": feature.description,
                "runtime_name": feature.runtime_name or feature.name,
                "domain": feature.domain,
                "owner": feature.owner if feature.owner == "ares" else (
                    "legacy" if feature.name in enabled else feature.owner
                ),
                "available": feature.name in enabled,
                "status": "available" if feature.name in enabled else "unavailable",
                "reason": "" if feature.name in enabled else local_reasons.get(
                    feature.name, "Not advertised by this backend"
                ),
            }
            for feature in FEATURE_REGISTRY
        },
        "capabilities": {name: name in enabled for name in UI_CAPABILITIES},
    }


def capabilities_for_backend(backend: str) -> dict[str, bool]:
    """Return stable UI flags while preserving the existing API shape."""
    return capability_contract_for_backend(backend)["capabilities"]
