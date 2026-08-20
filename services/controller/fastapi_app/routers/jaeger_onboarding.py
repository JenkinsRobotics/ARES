"""JaegerAI onboarding and peer-runtime status API endpoints.

JaegerAI is a peer product, not an in-process ARES library. Status probes use
the shared provider contract in ``api.providers.jaeger.status`` so Settings and
Control Center report the same truth as chat routing.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jaeger-onboarding", tags=["jaeger-onboarding"])


class CharacterInfo(BaseModel):
    """Character metadata for onboarding UI."""

    id: str
    name: str
    description: str
    role: str
    voice_tone: str
    voice_id: str


class CharacterListResponse(BaseModel):
    """Response for listing available JaegerAI characters."""

    characters: List[CharacterInfo]


class ModelRecommendation(BaseModel):
    """Model recommendation based on host tier.

    WARNING for UI consumers: these are *recommendations*, not installed or
    active models. Never display them as the current runtime model.
    """

    registry_key: str
    display_name: str
    size_gb: float
    score_pct: float
    tokens_per_task: int
    notes: str


class ModelListResponse(BaseModel):
    """Response for model recommendations (not live active-model state)."""

    awake: ModelRecommendation
    asleep: ModelRecommendation
    discovered: List[Dict[str, Any]]
    #: Explicit flag so clients never treat recommendations as live inventory.
    recommendations_only: bool = True


class OnboardingCompleteRequest(BaseModel):
    """Request to complete JaegerAI onboarding."""

    character_id: str
    agent_name: str
    role: str
    awake_model: str
    asleep_model: str | None = None
    voice_id: str | None = None


def _discover_instances() -> list[dict[str, Any]]:
    """Return the selected Jaeger instance without scanning its store."""
    try:
        from api.providers.jaeger.streaming import query_local_companion

        identity = query_local_companion("identity", {})
        serving = query_local_companion("serving_model", {})
    except Exception:
        return []
    if not isinstance(identity, dict):
        return []
    active = serving.get("serving") or serving.get("configured") if isinstance(serving, dict) else {}
    active = active if isinstance(active, dict) else {}
    instance = str(identity.get("instance") or identity.get("agent_name") or "").strip()
    if not instance:
        return []
    return [{
        "name": instance,
        "path": None,
        "display_name": str(identity.get("agent_name") or instance),
        "model": active.get("model"),
        "provider": active.get("provider"),
        "model_location": "local" if active.get("provider") in {"local", "in-process"} else "cloud",
        "character": identity.get("character"),
    }]


@router.get("/characters", response_model=CharacterListResponse)
async def list_jaeger_characters() -> CharacterListResponse:
    """List characters through Jaeger's bridge contract."""
    try:
        from api.providers.jaeger.companion import list_characters

        rows = list_characters()
    except Exception:
        rows = []
    return CharacterListResponse(characters=[
        CharacterInfo(
            id=str(row.get("id") or ""),
            name=str(row.get("name") or row.get("id") or ""),
            description=str(row.get("role") or ""),
            role=str(row.get("role") or ""),
            voice_tone=str(row.get("voice_tone") or ""),
            voice_id=str(row.get("voice_id") or ""),
        )
        for row in rows if isinstance(row, dict) and row.get("id")
    ])


@router.get("/models", response_model=ModelListResponse)
async def get_jaeger_model_recommendations() -> ModelListResponse:
    """Project Jaeger's model catalog without importing its source package."""
    try:
        from api.providers.jaeger.streaming import query_local_companion

        catalog = query_local_companion("model_catalog", {})
        rows = list(catalog.get("models") or []) if isinstance(catalog, dict) else []
        if not rows:
            raise RuntimeError("Jaeger returned no model inventory")
        awake_entry = rows[0]
        asleep_entry = rows[1] if len(rows) > 1 else rows[0]

        def recommendation(row: dict[str, Any]) -> ModelRecommendation:
            model_id = str(row.get("id") or row.get("label") or "unavailable")
            return ModelRecommendation(
                registry_key=model_id,
                display_name=str(row.get("label") or model_id),
                size_gb=float(row.get("size_gb") or 0),
                score_pct=float(row.get("score_pct") or 0),
                tokens_per_task=int(row.get("context_length") or 0),
                notes=str(row.get("notes") or row.get("status") or "Reported by JaegerAI"),
            )

        return ModelListResponse(
            awake=recommendation(awake_entry),
            asleep=recommendation(asleep_entry),
            discovered=rows,
            recommendations_only=True,
        )
    except Exception as e:
        logger.error("Failed to get model recommendations: %s", e)
        unavailable = ModelRecommendation(
            registry_key="unavailable", display_name="Unavailable", size_gb=0,
            score_pct=0, tokens_per_task=0,
            notes="Connect JaegerAI to load its model inventory.",
        )
        return ModelListResponse(
            awake=unavailable,
            asleep=unavailable,
            discovered=[],
            recommendations_only=True,
        )


@router.post("/create-instance")
async def create_jaeger_instance(request: OnboardingCompleteRequest) -> Dict[str, Any]:
    """Ask Jaeger to create its own instance through the onboarding service."""
    try:
        from api.providers.jaeger.companion import create_companion

        result = create_companion(
            character_id=request.character_id,
            name=request.agent_name,
            display_name=request.agent_name,
            role=request.role,
            voice_id=request.voice_id,
            awake_model=request.awake_model,
            asleep_model=request.asleep_model,
            make_default=True,
        )
        return {
            "success": True,
            "instance_name": result.get("name"),
            "instance_path": result.get("instance_dir"),
            "character": request.character_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create JaegerAI instance: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create instance: {str(e)}",
        ) from e


@router.get("/status")
async def get_jaeger_status(
    refresh: bool = Query(False, description="Bypass status cache and re-probe."),
) -> Dict[str, Any]:
    """Live JaegerAI peer status for Settings SI and diagnostics.

    Uses the shared provider status contract (gateway or local bridge) so the
    UI never invents "running" from a preference. Instance listing is best-effort
    filesystem discovery and is separate from transport readiness.
    """
    checked_at = time.time()
    from api.providers.jaeger.paths import is_jaeger_ai_root, jaeger_home, jaeger_launcher

    selected_root = jaeger_home()
    jaeger_cli = str(jaeger_launcher()) if jaeger_launcher().is_file() else None
    jaeger_ai_available = is_jaeger_ai_root(selected_root)
    jaeger_ai_path = str(selected_root) if jaeger_ai_available else None

    provider_state = "error"
    provider_available = False
    provider_message = "JaegerAI status could not be determined."
    provider_details: dict[str, Any] = {}
    try:
        from api.providers.jaeger.status import check_status, reset_cache

        if refresh:
            reset_cache()
        status = check_status(use_cache=not refresh)
        provider_state = status.state.value
        provider_available = bool(status.available)
        provider_message = status.message
        provider_details = dict(status.details or {})
    except Exception as exc:
        logger.debug("Provider status probe failed: %s", exc, exc_info=True)
        provider_state = "error"
        provider_available = False
        provider_message = f"JaegerAI status probe failed: {exc}"

    companion_ready = False
    try:
        from api.providers.jaeger.companion import companion_exists

        companion_ready = bool(companion_exists())
    except Exception:
        companion_ready = False

    instances = _discover_instances()

    # Map provider states onto explicit UI labels without collapsing failures.
    ui_state = {
        "connected": "ready",
        "needs_attention": "needs_attention",
        "offline": "installed_but_stopped",
        "not_installed": "not_installed",
        "not_configured": "misconfigured",
        "error": "error",
    }.get(provider_state, "unavailable")

    # Active model only when the live health probe reported one — never from
    # recommendation fallbacks.
    active_model = provider_details.get("model")
    from api.providers.jaeger.paths import jaeger_instance_name

    active_instance = provider_details.get("instance") or jaeger_instance_name()
    transport_mode = provider_details.get("mode")  # gateway | bridge
    gateway_url = provider_details.get("gateway_url")
    root = provider_details.get("root")

    return {
        "state": ui_state,
        "provider_state": provider_state,
        "available": provider_available,
        "message": provider_message,
        "details": provider_details,
        "checked_at": checked_at,
        "jaeger_cli": jaeger_cli,
        "jaeger_ai_available": jaeger_ai_available,
        "jaeger_ai_path": jaeger_ai_path,
        "companion_ready": companion_ready,
        "transport_mode": transport_mode,
        "gateway_url": gateway_url,
        "root": root,
        "active_model": active_model,
        "active_instance": active_instance,
        "instances": instances,
        "has_instances": len(instances) > 0,
        # Explicit non-recommendation marker for clients.
        "models_are_live": active_model is not None,
    }
