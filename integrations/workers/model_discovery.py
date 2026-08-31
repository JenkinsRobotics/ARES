"""Model inventory through owner APIs rather than worker filesystem scans."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from api.backends.catalog import model_entry

#: The Ollama Cloud registry. Matches
#: ``integrations.providers.ollama.context_probe.CLOUD_API_BASE``; both talk to
#: the same host for the same account.
CLOUD_API_BASE = "https://ollama.com"

#: The cloud catalog changes on the order of weeks, but this list is built from
#: ~20 network round trips, so it must never be rebuilt on a UI render. A hit
#: is cached long; a miss is retried sooner because it is usually transient
#: (offline, DNS blip) rather than an empty catalog.
_CLOUD_HIT_TTL = 3600.0
_CLOUD_MISS_TTL = 300.0
_CLOUD_CACHE: dict[str, tuple[list[dict[str, Any]], float]] = {}
_CLOUD_CACHE_LOCK = threading.Lock()


def reset_cloud_cache() -> None:
    """Drop the cached catalog. Exists so tests never share state."""
    with _CLOUD_CACHE_LOCK:
        _CLOUD_CACHE.clear()


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
        capabilities = {str(value).strip().lower() for value in row.get("capabilities") or []}
        remote = bool(row.get("remote_host") or row.get("remote_model")) or name.endswith(":cloud")
        # This inventory feeds an agent chat connection.  Exclude remote
        # cloud stubs and embedding-only artifacts from the Local catalog.
        suitable = "completion" in capabilities and "tools" in capabilities
        if name and not remote and suitable:
            result.append(model_entry(
                id=name, label=name, location="local", provider="ollama",
                source=url, notes="Installed local Ollama model.",
            ))
    return result


def _cloud_catalog_rows(*, base: str, timeout: float) -> list[dict[str, Any]]:
    """Model rows advertised by the Ollama Cloud registry itself."""

    url = base.rstrip("/") + "/api/tags"
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    return [row for row in (payload.get("models") or []) if isinstance(row, dict)]


def _cloud_capabilities(name: str, *, base: str, timeout: float) -> set[str] | None:
    """Capabilities for one cloud model, or ``None`` if they can't be read.

    ``/api/tags`` on the cloud registry omits capabilities entirely, unlike the
    local daemon's. ``None`` therefore means "unknown", which callers must not
    confuse with "no capabilities" -- filtering on an unknown would hide the
    entire catalog.
    """

    url = base.rstrip("/") + "/api/show"
    body = json.dumps({"model": name}).encode("utf-8")
    try:
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    raw = payload.get("capabilities")
    if not isinstance(raw, list):
        return None
    return {str(value).strip().lower() for value in raw}


def _cloud_ref(name: str) -> str:
    """The id Ollama serves a catalog model under, in the cloud.

    Ollama spells the cloud variant two ways depending on whether the name
    already carries a tag: ``minimax-m2.7`` becomes ``minimax-m2.7:cloud``,
    but ``gpt-oss:20b`` becomes ``gpt-oss:20b-cloud``.
    """
    if name.endswith(":cloud") or name.endswith("-cloud"):
        return name
    return f"{name}-cloud" if ":" in name else f"{name}:cloud"


def list_ollama_cloud_models(
    *,
    base_url: str = CLOUD_API_BASE,
    timeout: float = 6.0,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Models runnable in Ollama Cloud.

    Every model in the ollama.com catalog is cloud-runnable: pulling
    ``<name>:cloud`` registers a ~290-byte stub the daemon proxies to
    ollama.com, downloading no weights. Registering is instant and free, so
    these are offered as ordinary selectable models rather than gated behind a
    browse-only flag.

    Only the *bare* name would download weights (``deepseek-v4-pro:0813`` is
    893 GB), which is why every id here is the ``:cloud``/``-cloud`` spelling.
    """

    cache_key = base_url.rstrip("/")
    if use_cache:
        with _CLOUD_CACHE_LOCK:
            entry = _CLOUD_CACHE.get(cache_key)
        if entry is not None and entry[1] > time.monotonic():
            return list(entry[0])

    rows = _cloud_catalog_rows(base=base_url, timeout=timeout)
    result: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name") or row.get("model") or "").strip()
        if not name:
            continue
        ref = _cloud_ref(name)
        result.append(model_entry(
            id=ref, label=name, location="cloud", provider="ollama-cloud",
            source=base_url.rstrip("/") + "/api/tags",
            notes="Runs in Ollama Cloud; no local weights.",
        ))

    if use_cache:
        ttl = _CLOUD_HIT_TTL if result else _CLOUD_MISS_TTL
        with _CLOUD_CACHE_LOCK:
            _CLOUD_CACHE[cache_key] = (list(result), time.monotonic() + ttl)
    return result


def list_ollama_registered_cloud_models(
    *, base_url: str = "http://127.0.0.1:11434", timeout: float = 1.5,
) -> list[dict[str, Any]]:
    """Cloud models already registered on this daemon (ready with no pull)."""

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
        remote = bool(row.get("remote_host") or row.get("remote_model")) \
            or name.endswith(":cloud") or name.endswith("-cloud")
        if name and remote:
            result.append(model_entry(
                id=name, label=name, location="cloud", provider="ollama-cloud",
                source=url, notes="Runs in Ollama Cloud; registered locally.",
            ))
    return result


# These CLIs own model selection and do not expose a stable, bounded model-list
# command.  Returning an honest empty inventory is preferable to scraping their
# private settings or inventing selectable IDs.
def discover_claude_models() -> dict[str, Any] | None:
    return None


def discover_codex_models() -> dict[str, Any] | None:
    return None


def discover_gemini_local_models() -> dict[str, Any] | None:
    return None


def discover_grok_models() -> dict[str, Any] | None:
    return None


def discover_pi_local_models() -> dict[str, Any] | None:
    models = list_ollama_local_models()
    return {"models": models} if models else None


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


__all__ = [
    "discover_claude_models",
    "discover_codex_models",
    "discover_gemini_local_models",
    "discover_grok_models",
    "discover_jaeger_models",
    "discover_pi_local_models",
    "list_jaeger_installed_gguf",
    "list_ollama_cloud_models",
    "list_ollama_local_models",
    "list_ollama_registered_cloud_models",
    "reset_cloud_cache",
]
