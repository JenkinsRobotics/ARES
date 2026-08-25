"""Legacy provider compatibility router.

Preserves established provider API endpoints while routing their behavior to
ARES and negotiated worker adapters. The browser calls paths such as
/api/providers, /api/model/set, /api/default-model — this router
maps those to ARES equivalents or serves them directly.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from typing import Annotated

from ..request_context import RequestIdentity, require_identity, require_mutation_identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["provider-compat"], include_in_schema=False)


# ---------------------------------------------------------------------------
# /api/providers — Provider listing + key management (provider format)
# ---------------------------------------------------------------------------

def _ollama_local_models() -> list[dict[str, Any]]:
    """Fetch available models from the local Ollama server."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            if not name:
                continue
            details = m.get("details", {})
            caps = m.get("capabilities", [])
            # Skip embedding-only models
            if caps and all(c == "embedding" for c in caps):
                continue
            models.append({
                "id": name,
                "label": name,
                "provider": "ollama",
                "location": "local",
                "context_length": details.get("context_length", 0),
                "capabilities": caps,
                "size": m.get("size", 0),
                "remote_model": m.get("remote_model", ""),
            })
        return models
    except Exception:
        logger.debug("Ollama local model fetch failed", exc_info=True)
        return []


def _jaeger_models() -> list[dict[str, Any]]:
    """Return the model Jaeger reports as serving through its bridge."""
    try:
        from api.providers.jaeger.streaming import query_local_companion

        status = query_local_companion("serving_model", {})
        selection = status.get("serving") or status.get("configured") if isinstance(status, dict) else None
        if not isinstance(selection, dict):
            return []
        model = str(selection.get("model") or "").strip()
        if not model:
            return []
        provider = str(selection.get("provider") or "local").strip()
        return [{
            "id": model,
            "label": model,
            "provider": provider,
            "location": "local" if provider in {"local", "in-process"} else "cloud",
            "role": "primary",
        }]
    except Exception:
        logger.debug("Jaeger model fetch failed", exc_info=True)
        return []


def _runtime_credential_names() -> set[str]:
    """Read only Jaeger credential names; secret values stay in Jaeger."""
    try:
        from api.runtime_credentials import list_runtime_credentials

        return list_runtime_credentials()
    except Exception:
        logger.debug("Jaeger credential inventory failed", exc_info=True)
        return set()


@router.get("/providers")
def list_providers(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Return providers in the ARES provider format.

    This route performs bounded synchronous probes (Ollama and Jaeger).  A
    regular ``def`` route is intentional: FastAPI runs it in its worker pool,
    keeping one slow local runtime from freezing the ASGI event loop and every
    unrelated browser request.
    """
    ollama_local = _ollama_local_models()
    credential_names = _runtime_credential_names()
    jaeger_models = _jaeger_models()

    providers = []

    # Map of all provider credentials and models
    openai_key = "openai_api_key" in credential_names
    anthropic_key = "anthropic_api_key" in credential_names
    gemini_key = "gemini_api_key" in credential_names
    xai_key = "xai_api_key" in credential_names
    deepseek_key = "deepseek_api_key" in credential_names
    openrouter_key = "openrouter_api_key" in credential_names
    groq_key = "groq_api_key" in credential_names
    hf_token = "hf_token" in credential_names
    ollama_cloud_key = "ollama_cloud_api_key" in credential_names

    def _mask(configured: bool) -> str:
        return "••••••••" if configured else ""

    # 1. Jaeger AI (Active Local & Cloud Orchestrator)
    providers.append({
        "id": "jaeger",
        "display_name": "Jaeger AI (Active Brain)",
        "configurable": False,
        "is_oauth": False,
        "is_custom": False,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": True,
        "key_source": "jaeger_credential_store",
        "models": jaeger_models,
        "models_total": len(jaeger_models),
        "is_active": True,
    })

    # 2. Ollama Cloud
    has_cloud_key = bool(ollama_cloud_key)
    cloud_models: list[dict[str, Any]] = []
    providers.append({
        "id": "ollama-cloud",
        "display_name": "Ollama Cloud",
        "configurable": True,
        "is_oauth": False,
        "is_custom": True,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": has_cloud_key,
        "key_source": "jaeger_credential_store" if has_cloud_key else "none",
        "key_preview": _mask(ollama_cloud_key),
        "models": cloud_models,
        "models_total": len(cloud_models),
        "endpoint": "https://ollama.com/v1",
    })

    # 3. xAI (Grok)
    has_xai = bool(xai_key)
    providers.append({
        "id": "xai",
        "display_name": "xAI (Grok)",
        "configurable": True,
        "is_oauth": False,
        "is_custom": True,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": has_xai,
        "key_source": "jaeger_credential_store" if has_xai else "none",
        "key_preview": _mask(xai_key),
        "models": [{"id": "grok-4.6", "label": "Grok 4.6", "provider": "xai"}, {"id": "grok-2", "label": "Grok 2", "provider": "xai"}] if has_xai else [],
        "models_total": 2 if has_xai else 0,
        "endpoint": "https://api.x.ai/v1",
    })

    # 4. Ollama (Local)
    providers.append({
        "id": "ollama",
        "display_name": "Ollama (Local)",
        "configurable": False,
        "is_oauth": False,
        "is_custom": False,
        "is_self_hosted": True,
        "is_plugin_provider": False,
        "has_key": True,
        "key_source": "local",
        "models": ollama_local,
        "models_total": len(ollama_local),
        "endpoint": "http://localhost:11434",
    })

    # 5. OpenAI
    has_openai = bool(openai_key)
    providers.append({
        "id": "openai",
        "display_name": "OpenAI",
        "configurable": True,
        "is_oauth": False,
        "is_custom": True,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": has_openai,
        "key_source": "jaeger_credential_store" if has_openai else "none",
        "key_preview": _mask(openai_key),
        "models": [{"id": "gpt-4o", "label": "GPT-4o", "provider": "openai"}, {"id": "o3-mini", "label": "o3-mini", "provider": "openai"}] if has_openai else [],
        "models_total": 2 if has_openai else 0,
        "endpoint": "https://api.openai.com/v1",
    })

    # 6. Anthropic
    has_anthropic = bool(anthropic_key)
    providers.append({
        "id": "anthropic",
        "display_name": "Anthropic Claude",
        "configurable": True,
        "is_oauth": False,
        "is_custom": True,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": has_anthropic,
        "key_source": "jaeger_credential_store" if has_anthropic else "none",
        "key_preview": _mask(anthropic_key),
        "models": [{"id": "claude-3-5-sonnet", "label": "Claude 3.5 Sonnet", "provider": "anthropic"}] if has_anthropic else [],
        "models_total": 1 if has_anthropic else 0,
        "endpoint": "https://api.anthropic.com/v1",
    })

    # 7. Google Gemini
    has_gemini = bool(gemini_key)
    providers.append({
        "id": "gemini",
        "display_name": "Google Gemini",
        "configurable": True,
        "is_oauth": False,
        "is_custom": True,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": has_gemini,
        "key_source": "jaeger_credential_store" if has_gemini else "none",
        "key_preview": _mask(gemini_key),
        "models": [{"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash", "provider": "gemini"}] if has_gemini else [],
        "models_total": 1 if has_gemini else 0,
        "endpoint": "https://generativelanguage.googleapis.com/v1beta",
    })

    # 8. DeepSeek
    has_deepseek = bool(deepseek_key)
    providers.append({
        "id": "deepseek",
        "display_name": "DeepSeek",
        "configurable": True,
        "is_oauth": False,
        "is_custom": True,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": has_deepseek,
        "key_source": "jaeger_credential_store" if has_deepseek else "none",
        "key_preview": _mask(deepseek_key),
        "models": [{"id": "deepseek-chat", "label": "DeepSeek V3", "provider": "deepseek"}, {"id": "deepseek-reasoner", "label": "DeepSeek R1", "provider": "deepseek"}] if has_deepseek else [],
        "models_total": 2 if has_deepseek else 0,
        "endpoint": "https://api.deepseek.com/v1",
    })

    # 9. LM Studio (Local)
    providers.append({
        "id": "lmstudio",
        "display_name": "LM Studio (Local)",
        "configurable": True,
        "is_oauth": False,
        "is_custom": False,
        "is_self_hosted": True,
        "is_plugin_provider": False,
        "has_key": True,
        "key_source": "local",
        "models": [],
        "models_total": 0,
        "endpoint": "http://localhost:1234/v1",
    })

    # 10. OpenRouter
    has_openrouter = bool(openrouter_key)
    providers.append({
        "id": "openrouter",
        "display_name": "OpenRouter",
        "configurable": True,
        "is_oauth": False,
        "is_custom": True,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": has_openrouter,
        "key_source": "jaeger_credential_store" if has_openrouter else "none",
        "key_preview": _mask(openrouter_key),
        "models": [],
        "models_total": 0,
        "endpoint": "https://openrouter.ai/api/v1",
    })

    # 11. Groq
    has_groq = bool(groq_key)
    providers.append({
        "id": "groq",
        "display_name": "Groq",
        "configurable": True,
        "is_oauth": False,
        "is_custom": True,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": has_groq,
        "key_source": "jaeger_credential_store" if has_groq else "none",
        "key_preview": _mask(groq_key),
        "models": [],
        "models_total": 0,
        "endpoint": "https://api.groq.com/openai/v1",
    })

    # 12. Hugging Face
    has_hf = bool(hf_token)
    providers.append({
        "id": "huggingface",
        "display_name": "Hugging Face",
        "configurable": True,
        "is_oauth": False,
        "is_custom": True,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": has_hf,
        "key_source": "jaeger_credential_store" if has_hf else "none",
        "key_preview": _mask(hf_token),
        "models": [],
        "models_total": 0,
        "endpoint": "https://api-inference.huggingface.co",
    })

    return {"providers": providers}


@router.post("/providers")
async def save_provider_key(
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Save or remove a provider API key compatibility."""
    body = await request.json()
    provider_id = (body.get("provider") or "").strip()
    api_key = body.get("api_key")

    if not provider_id:
        return JSONResponse({"ok": False, "error": "Provider is required"}, status_code=400)

    # Map to the right credential store
    cred_map = {
        "ollama-cloud": "ollama_cloud_api_key",
        "huggingface": "hf_token",
        "xai": "xai_api_key",
        "openai": "openai_api_key",
        "anthropic": "anthropic_api_key",
        "gemini": "gemini_api_key",
        "deepseek": "deepseek_api_key",
        "openrouter": "openrouter_api_key",
        "groq": "groq_api_key",
        "mistral": "mistral_api_key",
    }

    cred_name = cred_map.get(provider_id)
    if not cred_name:
        return JSONResponse({"ok": False, "error": f"Unknown provider: {provider_id}"}, status_code=400)

    try:
        from api.runtime_credentials import delete_runtime_credential, set_runtime_credential

        if api_key is None or str(api_key).strip() == "":
            delete_runtime_credential(cred_name)
            return {"ok": True, "provider": provider_id, "action": "removed"}
        set_runtime_credential(cred_name, str(api_key).strip())
        return {"ok": True, "provider": provider_id, "action": "saved"}
    except Exception as e:
        from api.runtime_credentials import RuntimeCredentialError

        if isinstance(e, RuntimeCredentialError):
            return JSONResponse(
                {"ok": False, "error": str(e)}, status_code=e.status_code)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/providers/delete")
@router.delete("/providers")
async def delete_provider_key(
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Delete a provider API key."""
    from urllib.parse import parse_qs
    qs = parse_qs(request.url.query)
    provider_id = qs.get("provider", [""])[0]

    if not provider_id and request.method == "POST":
        try:
            body = await request.json()
            provider_id = (body.get("provider") or "").strip()
        except Exception:
            pass

    if not provider_id:
        return JSONResponse({"ok": False, "error": "Provider is required"}, status_code=400)

    cred_map = {
        "ollama-cloud": "ollama_cloud_api_key",
        "huggingface": "hf_token",
        "xai": "xai_api_key",
        "openai": "openai_api_key",
        "anthropic": "anthropic_api_key",
        "gemini": "gemini_api_key",
        "deepseek": "deepseek_api_key",
        "openrouter": "openrouter_api_key",
        "groq": "groq_api_key",
        "mistral": "mistral_api_key",
    }
    cred_name = cred_map.get(provider_id)
    if not cred_name:
        return JSONResponse({"ok": False, "error": f"Unknown provider: {provider_id}"}, status_code=400)

    try:
        from api.runtime_credentials import delete_runtime_credential

        delete_runtime_credential(cred_name)
        return {"ok": True, "provider": provider_id, "action": "deleted"}
    except Exception as e:
        from api.runtime_credentials import RuntimeCredentialError

        if isinstance(e, RuntimeCredentialError):
            return JSONResponse(
                {"ok": False, "error": str(e)}, status_code=e.status_code)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)



# ---------------------------------------------------------------------------
# /api/self-hosted/providers — Self-hosted provider management
# ---------------------------------------------------------------------------

@router.get("/providers/self-hosted")
async def list_self_hosted(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Return self-hosted provider configs (Ollama, LM Studio, etc.)."""
    return {
        "providers": [
            {
                "id": "ollama",
                "name": "Ollama",
                "base_url": "http://localhost:11434",
                "running": len(_ollama_local_models()) > 0,
            },
        ]
    }


# ---------------------------------------------------------------------------
# /api/default-model — Get/set the default model
# ---------------------------------------------------------------------------

@router.get("/default-model")
async def get_default_model(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Return the current default model."""
    try:
        from api.config import load_settings
        settings = load_settings()
        return {
            "model": settings.get("default_model") or "",
            "provider": settings.get("default_model_provider") or "",
        }
    except Exception:
        return {"model": "", "provider": ""}


# ---------------------------------------------------------------------------
# /api/models/refresh — Refresh model cache
# ---------------------------------------------------------------------------

@router.post("/models/refresh")
async def refresh_models(
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Invalidate and return ARES's native, runtime-filtered model catalog."""
    from api.config import get_available_models, invalidate_models_cache
    from api.model_catalog import filter_catalog_for_active_backend

    invalidate_models_cache()
    catalog = filter_catalog_for_active_backend(get_available_models())
    groups = list(catalog.get("groups") or [])
    total = sum(
        len(group.get("models") or []) + len(group.get("extra_models") or [])
        for group in groups
        if isinstance(group, dict)
    )
    return {"ok": True, **catalog, "groups": groups, "total": total}


# ---------------------------------------------------------------------------
# /api/onboarding/probe — Onboarding probe
# ---------------------------------------------------------------------------

@router.get("/onboarding/probe")
async def onboarding_probe(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Probe onboarding state compatibility."""
    try:
        from api.onboarding import get_onboarding_status
        status = get_onboarding_status()
        return {
            "needs_onboarding": not status.get("complete", False),
            "has_agent": True,
            "agent_name": "Jaeger AI",
            "backend": "jaeger_local",
            **status,
        }
    except Exception:
        return {
            "needs_onboarding": False,
            "has_agent": True,
            "agent_name": "Jaeger AI",
            "backend": "jaeger_local",
        }


# ---------------------------------------------------------------------------
# /api/updates/summary — Updates summary
# ---------------------------------------------------------------------------

@router.get("/updates/summary")
async def updates_summary(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Return update summary compatibility."""
    try:
        from api.updates import WEBUI_VERSION
        return {
            "current_version": WEBUI_VERSION or "dev",
            "update_available": False,
            "channel": "stable",
        }
    except Exception:
        return {"current_version": "dev", "update_available": False}


# ---------------------------------------------------------------------------
# /api/background — Background task status
# ---------------------------------------------------------------------------

@router.get("/background")
async def background_status_compat(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Return background task status compatibility."""
    try:
        from api.background_process import get_background_status
        return get_background_status()
    except Exception:
        return {"tasks": [], "running": False}


# ---------------------------------------------------------------------------
# /api/goal — Goal management
# ---------------------------------------------------------------------------

@router.get("/goal")
async def get_goal_compat(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
    session_id: str = "",
):
    """Get session goals compatibility."""
    if not session_id:
        return {"goals": []}
    try:
        from api.goals import get_session_goals
        return {"goals": get_session_goals(session_id) or []}
    except Exception:
        return {"goals": []}


__all__ = ["router"]
