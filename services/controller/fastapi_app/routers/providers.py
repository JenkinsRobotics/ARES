"""FastAPI Router for Provider Health & Dynamic Model Discovery."""

from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter
from pydantic import BaseModel, Field
from pathlib import Path
import os
from api.profiles import profile_env_for_active_request_readonly

router = APIRouter(prefix="/api/providers", tags=["providers"])


import time


def _format_eta(reset_ts: float | None) -> str | None:
    if not reset_ts:
        return None
    now = time.time()
    diff = reset_ts - now
    if diff <= 0:
        return "Ready now (pending refresh)"
    hours = int(diff // 3600)
    minutes = int((diff % 3600) // 60)
    if hours > 24:
        days = hours // 24
        rem_hours = hours % 24
        return f"Resets in {days}d {rem_hours}h"
    if hours > 0:
        return f"Resets in {hours}h {minutes}m"
    return f"Resets in {minutes}m"


class ProviderHealth(BaseModel):
    """Health status for a single provider."""
    id: str
    label: str
    status: str = "unknown"  # healthy | exhausted | missing | error
    details: str = ""
    model_count: int = 0
    reset_at: float | None = None
    reset_eta: str | None = None


class ProviderHealthResponse(BaseModel):
    """Response for GET /api/providers/health."""
    providers: List[ProviderHealth]
    healthy_count: int
    total_count: int


@router.get("/health", response_model=ProviderHealthResponse)
async def get_provider_health():
    """
    Live health check of all configured providers.
    Reads ~/.hermes/auth.json directly (not stale cache).
    Returns real-time status: healthy, exhausted, missing, or error.
    """
    hermes_home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    auth_path = hermes_home / "auth.json"
    
    providers: List[ProviderHealth] = []
    
    if not auth_path.exists():
        return ProviderHealthResponse(providers=[], healthy_count=0, total_count=0)
    
    import json
    auth = json.loads(auth_path.read_text()) if auth_path.exists() else {}
    
    # Check credential_pool
    pool = auth.get("credential_pool") or {}
    for name, entries in pool.items():
        if not isinstance(entries, list) or len(entries) == 0:
            providers.append(ProviderHealth(
                id=name,
                label=name,
                status="missing",
                details="No credentials configured"
            ))
            continue
        
        # Check for exhausted credentials
        usable = [e for e in entries if isinstance(e, dict) and e.get("last_status") != "exhausted"]
        if not usable:
            reset_ts = None
            for e in entries:
                if isinstance(e, dict) and e.get("last_error_reset_at"):
                    reset_ts = float(e["last_error_reset_at"])
                    break
            eta = _format_eta(reset_ts)
            providers.append(ProviderHealth(
                id=name,
                label=name,
                status="exhausted",
                details=f"Quota limit reached ({eta})" if eta else "All credentials exhausted",
                reset_at=reset_ts,
                reset_eta=eta
            ))
            continue
        
        providers.append(ProviderHealth(
            id=name,
            label=name,
            status="healthy",
            details=f"{len(usable)} active key(s)",
            model_count=len(usable)
        ))
    
    # Check OAuth providers
    oauth_providers = auth.get("providers") or {}
    for name, data in oauth_providers.items():
        if not isinstance(data, dict):
            continue
        
        # Skip if already in pool
        if any(p.id == name for p in providers):
            continue
        
        has_tokens = bool(data.get("tokens") or data.get("access_token"))
        last_error = data.get("last_auth_error") or {}
        
        if not has_tokens:
            providers.append(ProviderHealth(
                id=name,
                label=name,
                status="missing",
                details="No OAuth tokens"
            ))
        elif last_error.get("reason") == "credential_pool_refresh_failure":
            providers.append(ProviderHealth(
                id=name,
                label=name,
                status="exhausted",
                details=f"OAuth refresh failed: {last_error.get('message', 'Unknown')}"
            ))
        else:
            providers.append(ProviderHealth(
                id=name,
                label=name,
                status="healthy",
                details="OAuth active"
            ))
    
    # Check local Ollama
    try:
        import urllib.request
        req = urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2)
        if req.status == 200:
            providers.append(ProviderHealth(
                id="ollama",
                label="Ollama Local",
                status="healthy",
                details="Local daemon responding"
            ))
    except Exception:
        pass  # Don't add if not responding
    
    # Check Jaeger AI (Local instances, external cloud models, and gateway)
    jaeger_roots = [
        Path(os.environ.get("ARES_JAEGER_HOME", "")),
        Path(os.environ.get("JAEGER_HOME", "")),
        Path.home() / ".jaeger",
        Path.home() / ".jaeger_os",
        Path.home() / "jaeger",
        Path.home() / "JaegerAI",
    ]
    
    jaeger_status = "missing"
    jaeger_details = "Jaeger AI not configured"
    jaeger_models_count = 0
    
    for home in [r for r in jaeger_roots if r and r.is_dir()]:
        instance_dirs: list[Path] = []
        for base in (home / "instances", home / ".jaeger_os" / "instances"):
            if base.is_dir():
                for child in base.iterdir():
                    if child.is_dir():
                        instance_dirs.append(child)
        
        for inst_path in instance_dirs:
            cfg_path = inst_path / "config.yaml"
            if cfg_path.is_file():
                try:
                    import yaml
                    cfg = yaml.safe_load(cfg_path.read_text()) or {}
                    ext = cfg.get("external_model") or {}
                    if ext.get("enabled") and ext.get("model"):
                        jaeger_status = "healthy"
                        jaeger_details = f"External: {ext['model']} ({ext.get('provider', 'cloud')})"
                        jaeger_models_count += 1
                except Exception:
                    pass
        
        # Check for local GGUF models
        for models_base in (home / "models", home / ".jaeger_os" / "models"):
            if models_base.is_dir():
                ggufs = list(models_base.glob("**/*.gguf"))
                if ggufs:
                    jaeger_status = "healthy"
                    jaeger_details = f"{len(ggufs)} local GGUF model(s)"
                    jaeger_models_count += len(ggufs)
    
    # Try to ping gateway if available
    jaeger_gateway = os.environ.get("ARES_JAEGER_GATEWAY_URL") or "http://127.0.0.1:8000"
    try:
        import urllib.request
        req = urllib.request.urlopen(f"{jaeger_gateway}/health", timeout=1)
        if req.status == 200:
            jaeger_status = "healthy"
            jaeger_details = "Gateway active & responding"
    except Exception:
        pass
    
    if jaeger_status != "missing" or jaeger_models_count > 0:
        providers.append(ProviderHealth(
            id="jaeger_local",
            label="Jaeger AI",
            status=jaeger_status,
            details=jaeger_details,
            model_count=jaeger_models_count
        ))
    
    healthy_count = sum(1 for p in providers if p.status == "healthy")
    
    return ProviderHealthResponse(
        providers=sorted(providers, key=lambda p: (p.status != "healthy", p.id)),
        healthy_count=healthy_count,
        total_count=len(providers)
    )


@router.get("/models", response_model=Dict[str, Any])
async def get_filtered_models():
    """
    Get models filtered by live provider health.
    Only returns models from healthy providers.
    """
    from integrations.workers.model_discovery import discover_hermes_models
    from .providers import get_provider_health
    
    # Get live health status
    health_response = await get_provider_health()
    healthy_providers = {p.id for p in health_response.providers if p.status == "healthy"}
    
    # Get all models
    all_models = discover_hermes_models()
    
    # Filter to healthy providers only
    filtered_models = [
        m for m in all_models.get("models", [])
        if m.get("provider") in healthy_providers or m.get("provider") == "ollama"
    ]
    
    return {
        "models": filtered_models,
        "healthy_providers": sorted(healthy_providers),
        "total_models": len(filtered_models),
        "filtered_out": len(all_models.get("models", [])) - len(filtered_models)
    }
