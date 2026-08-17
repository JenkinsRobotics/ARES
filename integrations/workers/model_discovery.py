"""Model inventory through owner APIs rather than worker filesystem scans."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from api.backends.catalog import model_entry


def list_ollama_local_models(
    *, base_url: str = "http://127.0.0.1:11434", timeout: float = 1.5,
) -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + "/api/tags"
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    result: list[dict[str, Any]] = []
    for row in payload.get("models") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("model") or "").strip()
        if name:
            result.append(model_entry(
                id=name, label=name, location="local", provider="ollama",
                source=url, notes="Installed local Ollama model.",
            ))
    return result


def discover_jaeger_models(**_ignored: Any) -> dict[str, Any]:
    """Ask Jaeger for its model catalog over the versioned bridge."""
    try:
        from api.providers.jaeger.streaming import query_local_companion

        payload = query_local_companion("model_catalog", {})
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    serving = payload.get("serving") if isinstance(payload.get("serving"), dict) else {}
    return {
        "models": list(payload.get("models") or []),
        "providers": list(payload.get("providers") or []),
        "default": serving,
    }


def list_jaeger_installed_gguf(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
    """Compatibility surface backed by Jaeger's model catalog."""
    return [
        row for row in discover_jaeger_models()["models"]
        if isinstance(row, dict) and row.get("location") == "local"
    ]


__all__ = ["discover_jaeger_models", "list_jaeger_installed_gguf", "list_ollama_local_models"]
