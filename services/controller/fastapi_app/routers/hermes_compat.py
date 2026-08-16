"""Hermes-UI compatibility router.

Bridges the Hermes WebUI's expected API endpoints to the ARES+Jaeger
backend. The Hermes UI (vanilla JS) calls Hermes-era API paths like
/api/providers, /api/model/set, /api/default-model — this router
maps those to ARES equivalents or serves them directly.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from typing import Annotated

from ..request_context import RequestIdentity, require_identity, require_mutation_identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["hermes-compat"], include_in_schema=False)


# ---------------------------------------------------------------------------
# /api/providers — Provider listing + key management (Hermes format)
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


def _ollama_cloud_models(api_key: str | None) -> list[dict[str, Any]]:
    """Fetch available models from Ollama Cloud."""
    if not api_key:
        return []
    try:
        req = urllib.request.Request(
            "https://ollama.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        models = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            if not mid:
                continue
            models.append({
                "id": mid,
                "label": mid,
                "provider": "ollama-cloud",
                "location": "cloud",
            })
        return models
    except Exception:
        logger.debug("Ollama Cloud model fetch failed", exc_info=True)
        return []


def _jaeger_models() -> list[dict[str, Any]]:
    """Fetch models from the active Jaeger AI instance config."""
    models = []
    try:
        # Read the Jaeger instance config
        jaeger_home = os.environ.get("ARES_JAEGER_HOME") or os.environ.get("JAEGER_HOME") or ""
        if not jaeger_home:
            # Try the default path
            import pathlib
            jaeger_home = str(pathlib.Path.home() / "GitHub" / "JaegerAI")

        config_path = os.path.join(jaeger_home, ".jaeger_os/instances/jarvis/config.yaml")
        if not os.path.isfile(config_path):
            return models

        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        # External (cloud) model
        ext = cfg.get("external_model", {})
        if ext.get("enabled"):
            models.append({
                "id": ext.get("model", ""),
                "label": f"{ext.get('model', '')} (cloud)",
                "provider": ext.get("provider", ""),
                "location": "cloud",
                "role": "primary",
            })

        # Local model
        model_cfg = cfg.get("model", {})
        mp = model_cfg.get("model_path", "")
        if mp:
            import pathlib
            label = pathlib.Path(mp).name
            models.append({
                "id": f"local:{label}",
                "label": f"{label} (local fallback)",
                "provider": model_cfg.get("backend", "local"),
                "location": "local",
                "role": "fallback",
            })
    except Exception:
        logger.debug("Jaeger model fetch failed", exc_info=True)
    return models


def _read_jaeger_credential(name: str) -> str:
    """Read a credential from the Jaeger instance credentials store."""
    try:
        import pathlib
        cred_path = pathlib.Path.home() / "GitHub/JaegerAI/.jaeger_os/instances/jarvis/credentials" / name
        if cred_path.is_file():
            return cred_path.read_text().strip()
    except Exception:
        pass
    return ""


@router.get("/providers")
async def list_providers(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Return providers in the Hermes UI format."""
    ollama_local = _ollama_local_models()
    ollama_cloud_key = _read_jaeger_credential("ollama_cloud_api_key")
    ollama_cloud = _ollama_cloud_models(ollama_cloud_key)
    jaeger_models = _jaeger_models()

    providers = []

    # Jaeger AI (the active ARES backend)
    providers.append({
        "id": "jaeger",
        "display_name": "Jaeger AI",
        "configurable": False,
        "is_oauth": False,
        "is_custom": False,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": True,
        "key_source": "config_yaml",
        "models": jaeger_models,
        "models_total": len(jaeger_models),
        "is_active": True,
    })

    # Map of all provider credentials and models
    openai_key = os.environ.get("OPENAI_API_KEY") or _read_jaeger_credential("openai_api_key")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or _read_jaeger_credential("anthropic_api_key")
    gemini_key = os.environ.get("GEMINI_API_KEY") or _read_jaeger_credential("gemini_api_key")
    xai_key = os.environ.get("XAI_API_KEY") or _read_jaeger_credential("xai_api_key")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY") or _read_jaeger_credential("deepseek_api_key")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY") or _read_jaeger_credential("openrouter_api_key")
    groq_key = os.environ.get("GROQ_API_KEY") or _read_jaeger_credential("groq_api_key")
    mistral_key = os.environ.get("MISTRAL_API_KEY") or _read_jaeger_credential("mistral_api_key")
    hf_token = os.environ.get("HF_TOKEN") or _read_jaeger_credential("hf_token")

    def _mask(k: str) -> str:
        if not k:
            return ""
        return k[:4] + "••••••••" + k[-4:] if len(k) > 10 else "••••••••"

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
        "key_source": "config_yaml",
        "models": jaeger_models,
        "models_total": len(jaeger_models),
        "is_active": True,
    })

    # 2. Ollama Cloud
    has_cloud_key = bool(ollama_cloud_key)
    cloud_models = ollama_cloud if has_cloud_key else []
    providers.append({
        "id": "ollama-cloud",
        "display_name": "Ollama Cloud",
        "configurable": True,
        "is_oauth": False,
        "is_custom": True,
        "is_self_hosted": False,
        "is_plugin_provider": False,
        "has_key": has_cloud_key,
        "key_source": "api_key" if has_cloud_key else "none",
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
        "key_source": "api_key" if has_xai else "none",
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
        "key_source": "api_key" if has_openai else "none",
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
        "key_source": "api_key" if has_anthropic else "none",
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
        "key_source": "api_key" if has_gemini else "none",
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
        "key_source": "api_key" if has_deepseek else "none",
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
        "key_source": "api_key" if has_openrouter else "none",
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
        "key_source": "api_key" if has_groq else "none",
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
        "key_source": "env" if os.environ.get("HF_TOKEN") else ("api_key" if has_hf else "none"),
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
    """Save or remove a provider API key (Hermes compatibility)."""
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
        import pathlib
        jaeger_dir = pathlib.Path.home() / "GitHub/JaegerAI/.jaeger_os/instances/jarvis/credentials"
        ares_dir = pathlib.Path.home() / ".ares/credentials"
        jaeger_dir.mkdir(parents=True, exist_ok=True)
        ares_dir.mkdir(parents=True, exist_ok=True)

        if api_key is None or str(api_key).strip() == "":
            for root in [jaeger_dir, ares_dir]:
                f = root / cred_name
                if f.exists():
                    f.unlink()
            return {"ok": True, "provider": provider_id, "action": "removed"}

        str_key = str(api_key).strip()
        (jaeger_dir / cred_name).write_text(str_key)
        (ares_dir / cred_name).write_text(str_key)

        return {"ok": True, "provider": provider_id, "action": "saved"}
    except Exception as e:
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
        import pathlib
        for root in [pathlib.Path.home() / "GitHub/JaegerAI/.jaeger_os/instances/jarvis/credentials", pathlib.Path.home() / ".ares/credentials"]:
            f = root / cred_name
            if f.exists():
                f.unlink()
        return {"ok": True, "provider": provider_id, "action": "deleted"}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)



# ---------------------------------------------------------------------------
# /api/channels & /api/messaging/platforms — Channel Adapter management
# ---------------------------------------------------------------------------

@router.get("/channels")
@router.get("/messaging/platforms")
async def list_channels(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Return available and configured messaging channel adapters."""
    from api.gateway_status import gateway_status_payload
    gateway_info = gateway_status_payload()
    configured_names = {p.get("name") for p in gateway_info.get("platforms", []) if isinstance(p, dict)}

    all_channels = [
        {
            "id": "telegram",
            "name": "Telegram",
            "state": "connected" if "telegram" in configured_names else "not_configured",
            "description": "Telegram Bot Integration with QR onboarding & webhook routing",
            "env_vars": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS"],
            "configured": "telegram" in configured_names,
        },
        {
            "id": "slack",
            "name": "Slack",
            "state": "connected" if "slack" in configured_names else "not_configured",
            "description": "Slack Socket Mode / App Token workspace bot",
            "env_vars": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_ALLOWED_USERS"],
            "configured": "slack" in configured_names,
        },
        {
            "id": "discord",
            "name": "Discord",
            "state": "connected" if "discord" in configured_names else "not_configured",
            "description": "Discord Gateway Bot with multi-channel and DM support",
            "env_vars": ["DISCORD_BOT_TOKEN", "DISCORD_ALLOWED_CHANNELS"],
            "configured": "discord" in configured_names,
        },
        {
            "id": "whatsapp",
            "name": "WhatsApp",
            "state": "connected" if "whatsapp" in configured_names else "not_configured",
            "description": "WhatsApp Business Cloud API / QR Pairing Bridge",
            "env_vars": ["WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"],
            "configured": "whatsapp" in configured_names,
        },
        {
            "id": "teams",
            "name": "Microsoft Teams",
            "state": "connected" if "teams" in configured_names else "not_configured",
            "description": "Microsoft Graph & Azure Bot Service connector",
            "env_vars": ["TEAMS_APP_ID", "TEAMS_APP_PASSWORD"],
            "configured": "teams" in configured_names,
        },
        {
            "id": "matrix",
            "name": "Matrix",
            "state": "connected" if "matrix" in configured_names else "not_configured",
            "description": "Matrix Synapse / Element decentralized chat bridge",
            "env_vars": ["MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN", "MATRIX_USER_ID"],
            "configured": "matrix" in configured_names,
        },
        {
            "id": "email",
            "name": "Email (SMTP / IMAP)",
            "state": "connected" if "email" in configured_names else "not_configured",
            "description": "Inbound/outbound email polling and dispatch",
            "env_vars": ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "IMAP_HOST"],
            "configured": "email" in configured_names,
        },
    ]

    return {
        "ok": True,
        "platforms": all_channels,
        "gateway": gateway_info,
    }


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
# /api/model/set — Set the active model for the current session
# ---------------------------------------------------------------------------

@router.post("/model/set")
async def set_model(
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Set the model for a session (Hermes compatibility)."""
    body = await request.json()
    session_id = body.get("session_id", "")
    model = body.get("model", "")
    model_provider = body.get("model_provider", "")

    if not session_id:
        return JSONResponse({"ok": False, "error": "session_id required"}, status_code=400)

    try:
        from api.models import get_session
        session = get_session(session_id)
        if model:
            session.model = model
        if model_provider:
            session.model_provider = model_provider
        return {"ok": True, "model": model, "model_provider": model_provider}
    except KeyError:
        return JSONResponse({"ok": False, "error": "Session not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# /api/models/refresh — Refresh model cache
# ---------------------------------------------------------------------------

@router.post("/models/refresh")
async def refresh_models(
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Refresh the model cache (returns fresh model list)."""
    ollama_local = _ollama_local_models()
    ollama_cloud_key = _read_jaeger_credential("ollama_cloud_api_key")
    ollama_cloud = _ollama_cloud_models(ollama_cloud_key)
    jaeger_models = _jaeger_models()

    groups = []
    if jaeger_models:
        groups.append({
            "provider": "jaeger",
            "label": "Jaeger AI",
            "models": jaeger_models,
        })
    if ollama_cloud:
        groups.append({
            "provider": "ollama-cloud",
            "label": "Ollama Cloud",
            "models": ollama_cloud,
        })
    if ollama_local:
        groups.append({
            "provider": "ollama",
            "label": "Ollama (Local)",
            "models": ollama_local,
        })

    return {
        "ok": True,
        "groups": groups,
        "total": len(jaeger_models) + len(ollama_cloud) + len(ollama_local),
    }


# ---------------------------------------------------------------------------
# /api/personality/set — Set the active personality
# ---------------------------------------------------------------------------

@router.post("/personality/set")
async def set_personality(
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Set the active personality (Hermes compatibility → ARES persona)."""
    body = await request.json()
    personality = body.get("personality", "")

    try:
        from api.config import save_settings
        save_settings({"active_personality": personality})
        return {"ok": True, "personality": personality}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# /api/profile/switch — Switch active profile
# ---------------------------------------------------------------------------

@router.post("/profile/switch")
async def switch_profile(
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Switch the active profile (Hermes compatibility)."""
    body = await request.json()
    profile = body.get("profile", "")

    try:
        from api.profiles import set_active_profile
        set_active_profile(profile)
        return {"ok": True, "profile": profile}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# /api/profile/create — Create a new profile
# ---------------------------------------------------------------------------

@router.post("/profile/create")
async def create_profile(
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Create a new profile (Hermes compatibility)."""
    body = await request.json()
    name = body.get("name", "")

    if not name:
        return JSONResponse({"ok": False, "error": "name required"}, status_code=400)

    try:
        from api.profiles import create_profile as _create
        _create(name)
        return {"ok": True, "profile": name}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# /api/profile/delete — Delete a profile
# ---------------------------------------------------------------------------

@router.post("/profile/delete")
async def delete_profile(
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Delete a profile (Hermes compatibility)."""
    body = await request.json()
    name = body.get("name", "")

    try:
        from api.profiles import delete_profile as _delete
        _delete(name)
        return {"ok": True, "deleted": name}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# /api/notes/search — Search notes (compatibility shim)
# ---------------------------------------------------------------------------

@router.get("/notes/search")
async def search_notes_compat(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
    q: str = "",
):
    """Search notes (Hermes compatibility → ARES notes)."""
    if not q:
        return {"results": []}
    try:
        from api.notes import search_notes
        results = search_notes(q)
        return {"results": results or []}
    except Exception:
        return {"results": []}


# ---------------------------------------------------------------------------
# /api/onboarding/probe — Onboarding probe
# ---------------------------------------------------------------------------

@router.get("/onboarding/probe")
async def onboarding_probe(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Probe onboarding state (Hermes compatibility)."""
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
# /api/onboarding/complete — Complete onboarding
# ---------------------------------------------------------------------------

@router.post("/onboarding/complete")
async def onboarding_complete(
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Mark onboarding as complete (Hermes compatibility)."""
    try:
        from api.onboarding import mark_onboarding_complete
        mark_onboarding_complete()
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# /api/updates/summary — Updates summary
# ---------------------------------------------------------------------------

@router.get("/updates/summary")
async def updates_summary(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Return update summary (Hermes compatibility)."""
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
# /api/session/new — Create new session (POST)
# ---------------------------------------------------------------------------

@router.post("/session/new")
async def create_session_compat(
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Create a new session (Hermes compatibility)."""
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    try:
        from api.models import create_session
        session = create_session(
            profile=getattr(_identity, "profile", None),
            **{k: v for k, v in body.items() if k in ("model", "model_provider", "workspace", "title")},
        )
        return {
            "session_id": session.session_id,
            "title": getattr(session, "title", "New Conversation"),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# /api/background — Background task status
# ---------------------------------------------------------------------------

@router.get("/background")
async def background_status_compat(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    """Return background task status (Hermes compatibility)."""
    try:
        from api.background_process import get_background_status
        return get_background_status()
    except Exception:
        return {"tasks": [], "running": False}


# ---------------------------------------------------------------------------
# /api/transcribe — Audio transcription
# ---------------------------------------------------------------------------

@router.post("/transcribe")
async def transcribe_compat(
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Audio transcription stub (Hermes compatibility)."""
    return JSONResponse(
        {"error": "Transcription not available in ARES mode", "ok": False},
        status_code=501,
    )


# ---------------------------------------------------------------------------
# /api/goal — Goal management
# ---------------------------------------------------------------------------

@router.get("/goal")
async def get_goal_compat(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
    session_id: str = "",
):
    """Get session goals (Hermes compatibility)."""
    if not session_id:
        return {"goals": []}
    try:
        from api.goals import get_session_goals
        return {"goals": get_session_goals(session_id) or []}
    except Exception:
        return {"goals": []}


# ---------------------------------------------------------------------------
# /api/share/create — Create a share link
# ---------------------------------------------------------------------------

@router.post("/share/create")
async def create_share_compat(
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Create a share link (Hermes compatibility → ARES shares)."""
    body = await request.json()
    session_id = body.get("session_id", "")
    try:
        from api.shares import create_share
        share = create_share(session_id)
        return {"ok": True, "share_id": share.get("id", ""), "url": share.get("url", "")}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# /api/wiki/browse — Browse wiki
# ---------------------------------------------------------------------------

@router.get("/wiki/browse")
async def wiki_browse_compat(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
    path: str = "",
):
    """Browse wiki pages (Hermes compatibility)."""
    try:
        from api.wiki import browse_wiki
        return browse_wiki(path) or {"pages": [], "path": path}
    except Exception:
        return {"pages": [], "path": path}


__all__ = ["router"]
