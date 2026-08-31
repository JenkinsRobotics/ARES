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
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from api.system_health import build_system_health_payload

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 1.0
_cached_stats: dict[str, Any] | None = None
_cached_time: float = 0.0


def _bytes_view(value: int) -> dict[str, Any]:
    amount = max(0, int(value or 0))
    return {"bytes": amount, "gb": round(amount / (1024**3), 2)}


def _macos_memory_details() -> dict[str, Any]:
    """Return read-only VM counters that Stats also derives from macOS.

    Stats has no supported local API or AppleScript dictionary.  Reading the
    OS counters directly avoids coupling ARES to the app's private privileged
    helper while producing the same class of telemetry.
    """
    if sys.platform != "darwin":
        return {}
    try:
        completed = subprocess.run(
            ["/usr/bin/vm_stat"], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=2, check=False,
        )
        if completed.returncode != 0:
            return {}
        lines = completed.stdout.splitlines()
        page_match = re.search(r"page size of (\d+) bytes", lines[0] if lines else "")
        if not page_match:
            return {}
        page_size = int(page_match.group(1))
        pages: dict[str, int] = {}
        for line in lines[1:]:
            key, marker, raw = line.partition(":")
            if not marker:
                continue
            digits = re.sub(r"[^0-9]", "", raw)
            if digits:
                pages[key.strip()] = int(digits)
        return {
            "compressed": _bytes_view(pages.get("Pages occupied by compressor", 0) * page_size),
            "wired": _bytes_view(pages.get("Pages wired down", 0) * page_size),
            "free": _bytes_view(
                (pages.get("Pages free", 0) + pages.get("Pages speculative", 0)) * page_size
            ),
        }
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def _host_resource_details() -> dict[str, Any]:
    try:
        import psutil

        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
    except Exception:
        return {}
    memory = {
        "available": _bytes_view(getattr(vm, "available", 0)),
        "free": _bytes_view(getattr(vm, "free", 0)),
        "active": _bytes_view(getattr(vm, "active", 0)),
        "inactive": _bytes_view(getattr(vm, "inactive", 0)),
        "wired": _bytes_view(getattr(vm, "wired", 0)),
    }
    memory.update(_macos_memory_details())
    try:
        load_average = [round(float(value), 2) for value in os.getloadavg()]
    except (AttributeError, OSError):
        load_average = []
    return {
        "memory_breakdown": memory,
        "swap": {
            **_bytes_view(getattr(swap, "used", 0)),
            "total": _bytes_view(getattr(swap, "total", 0)),
            "free": _bytes_view(getattr(swap, "free", 0)),
            "percent": round(float(getattr(swap, "percent", 0.0) or 0.0), 1),
        },
        "cpu_count": int(psutil.cpu_count(logical=True) or 0),
        "load_average": load_average,
        "metrics_source": "macos-native+psutil" if sys.platform == "darwin" else "os-native+psutil",
    }


def _top_processes(limit: int) -> list[dict[str, Any]]:
    """Rank processes by resident memory without exposing arguments or users."""
    try:
        import psutil
    except Exception:
        return []
    total = int(getattr(psutil.virtual_memory(), "total", 0) or 0)
    rows: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = process.info
            rss = int(getattr(info.get("memory_info"), "rss", 0) or 0)
            if rss <= 0:
                continue
            rows.append({
                "pid": int(info.get("pid") or 0),
                "name": str(info.get("name") or "unknown")[:200],
                "memory_bytes": rss,
                "memory_gb": round(rss / (1024**3), 2),
                "memory_percent": round((rss / total) * 100.0, 1) if total else 0.0,
            })
        except (psutil.Error, OSError, ValueError):
            continue
    rows.sort(key=lambda row: (-row["memory_bytes"], row["pid"]))
    return rows[: max(1, min(int(limit), 25))]


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


def get_system_stats(
    profile_name: str | None = None,
    force_refresh: bool = False,
    *,
    include_processes: bool = False,
    process_limit: int = 10,
) -> dict[str, Any]:
    """Return enriched telemetry payload with host metrics and AI runtimes."""
    global _cached_stats, _cached_time

    now = time.time()
    if not force_refresh and _cached_stats is not None and (now - _cached_time) < _CACHE_TTL_SECONDS:
        payload = deepcopy(_cached_stats)
        if include_processes:
            payload["host"]["top_processes"] = _top_processes(process_limit)
        return payload

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

    host = {
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
        **_host_resource_details(),
    }
    payload = {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": active_profile,
        "host": host,
        "ai_runtimes": {
            "ollama": ollama_info,
            "jaeger": jaeger_info,
            "active_model_in_vram": ollama_info["models"][0]["name"] if ollama_info["models"] else None,
            "is_local_model_loaded": ollama_info["loaded_models_count"] > 0,
        },
    }

    _cached_stats = payload
    _cached_time = now
    result = deepcopy(payload)
    if include_processes:
        result["host"]["top_processes"] = _top_processes(process_limit)
    return result
