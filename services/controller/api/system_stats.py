"""Safe aggregate system, host resources, and local AI model telemetry.

Surfaces:
- Host CPU, RAM (used/total), Disk
- Local Model Engine Status (Ollama VRAM allocation, loaded models)
- Jaeger AI Bridge status
- Active Persona / Profile status (e.g. Jarvis)
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any

from api.system_health import build_system_health_payload

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 1.0
_cached_stats: dict[str, Any] | None = None
_cached_time: float = 0.0


def _query_ollama_ps(host: str = "http://127.0.0.1:11434") -> dict[str, Any]:
    """Query Ollama's /api/ps endpoint to check running models in VRAM."""
    url = f"{host.rstrip('/')}/api/ps"
    req = urllib.request.Request(url, headers={"User-Agent": "ARES-System-Stats/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=0.5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                models = data.get("models", [])
                loaded_models = []
                total_vram = 0
                for m in models:
                    size_vram = m.get("size_vram", m.get("size", 0))
                    total_vram += size_vram
                    loaded_models.append({
                        "name": m.get("name", "unknown"),
                        "model": m.get("model", ""),
                        "size_bytes": m.get("size", 0),
                        "size_vram_bytes": size_vram,
                        "size_vram_formatted": f"{round(size_vram / (1024**3), 2)} GB" if size_vram >= 1024**3 else f"{round(size_vram / (1024**2), 1)} MB",
                        "expires_at": m.get("expires_at"),
                        "details": m.get("details", {}),
                    })
                return {
                    "available": True,
                    "status": "loaded" if loaded_models else "ready_idle",
                    "loaded_models_count": len(loaded_models),
                    "total_vram_bytes": total_vram,
                    "total_vram_formatted": f"{round(total_vram / (1024**3), 2)} GB",
                    "models": loaded_models,
                }
    except Exception:
        # Ollama offline or not running
        pass
    return {
        "available": False,
        "status": "offline",
        "loaded_models_count": 0,
        "total_vram_bytes": 0,
        "total_vram_formatted": "0 GB",
        "models": [],
    }


def _query_jaeger_status() -> dict[str, Any]:
    """Check Jaeger AI bridge connectivity and status."""
    try:
        from api.providers.jaeger import status as jaeger_status
        stat = jaeger_status.check_status(use_cache=True)
        status_val = (
            stat.state.value
            if hasattr(stat, "state") and hasattr(stat.state, "value")
            else "connected" if stat.available else "unreachable"
        )
        return {
            "available": stat.available,
            "status": status_val,
            "runtime_owner": "jaeger",
            "message": stat.message,
            "details": stat.details if hasattr(stat, "details") else {},
        }
    except Exception as exc:
        return {
            "available": False,
            "status": "unavailable",
            "runtime_owner": "jaeger",
            "message": f"Jaeger probe error: {exc}",
            "details": {},
        }


def get_system_stats(profile_name: str | None = None, force_refresh: bool = False) -> dict[str, Any]:
    """Return enriched telemetry payload with host metrics and AI runtimes."""
    global _cached_stats, _cached_time

    now = time.time()
    if not force_refresh and _cached_stats is not None and (now - _cached_time) < _CACHE_TTL_SECONDS:
        return _cached_stats

    health_payload = build_system_health_payload()
    ollama_info = _query_ollama_ps()
    jaeger_info = _query_jaeger_status()

    # Format human-friendly memory
    mem_dict = health_payload.get("memory") or {}
    mem_used = mem_dict.get("used_bytes", 0)
    mem_total = mem_dict.get("total_bytes", 0)
    mem_percent = mem_dict.get("percent", 0.0)

    cpu_dict = health_payload.get("cpu") or {}
    cpu_percent = cpu_dict.get("percent", 0.0)

    # Active persona / profile
    active_profile = profile_name or os.getenv("ARES_ACTIVE_PROFILE", "Jarvis")

    payload = {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": active_profile,
        "host": {
            "cpu_percent": cpu_percent,
            "memory": {
                "percent": mem_percent,
                "used_gb": round(mem_used / (1024**3), 2),
                "total_gb": round(mem_total / (1024**3), 2),
                "used_bytes": mem_used,
                "total_bytes": mem_total,
                "formatted": f"{round(mem_used / (1024**3), 1)} / {round(mem_total / (1024**3), 1)} GB",
            },
            "disk": health_payload.get("disk"),
        },
        "ai_runtimes": {
            "ollama": ollama_info,
            "jaeger": jaeger_info,
            "active_model_in_vram": ollama_info["models"][0]["name"] if ollama_info["models"] else None,
            "is_local_model_loaded": ollama_info["loaded_models_count"] > 0,
        },
    }

    _cached_stats = payload
    _cached_time = now
    return payload
