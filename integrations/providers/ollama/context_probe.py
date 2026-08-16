"""True context windows, read from Ollama instead of guessed.

Ollama is the one provider in this stack that publishes a model's real
context window over its API — and it does so for cloud models too:
``model_info["<arch>.context_length"]`` on ``/api/show``. Everything
else in ARES falls back to :func:`api.model_context._estimate_model_context_length`,
a substring table where anything matching ``"deepseek"`` answers 131072.
For ``deepseek-v4-pro`` the real number is 1048576 — an 8x undercount,
which silently caps compaction thresholds, the WebUI context ring, and
the ``ctx`` ARES syncs into JaegerAI's config.

Two endpoints, because a cloud model the operator never pulled is not
known to the local daemon:

  - ``<OLLAMA_HOST>/api/show`` — local models, plus cloud models that
    have been pulled (those carry a ``-cloud``/``:cloud`` tag locally).
  - ``https://ollama.com/api/show`` — authoritative for every cloud id,
    and needs the API key.

Local is tried first so an offline machine still resolves its own
models without reaching for the network. Both are best-effort: any
failure returns 0 and the caller falls back to its own guess.

Results are cached in-process (windows are a property of the model, not
of the moment) and failures are cached briefly too, so a stopped daemon
costs one timeout per five minutes rather than one per turn.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

CLOUD_API_BASE = "https://ollama.com"

_LOCAL_TIMEOUT = 2.0
_CLOUD_TIMEOUT = 6.0

# Windows don't change under a fixed model id; a long TTL is honest.
_HIT_TTL = 3600.0
# A miss can be transient (daemon starting, network blip) — retry sooner
# than a hit expires, but not on every turn.
_MISS_TTL = 300.0

_CACHE: dict[str, tuple[int, float]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_get(key: str) -> int | None:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() >= expires_at:
        return None
    return value


def _cache_put(key: str, value: int) -> None:
    ttl = _HIT_TTL if value > 0 else _MISS_TTL
    with _CACHE_LOCK:
        _CACHE[key] = (value, time.time() + ttl)


def reset_cache() -> None:
    """Drop every cached window. For tests and for an explicit refresh."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _local_base_url() -> str:
    """Ollama's HTTP root, honouring ``OLLAMA_HOST``.

    Reuses the provider's own resolver when it imports cleanly, so a
    remote or non-default daemon is respected here exactly as it is for
    status checks. Falls back to the documented default otherwise —
    a probe must never be the reason a turn fails.
    """
    try:
        from api.providers.ollama.status import base_url

        resolved = str(base_url() or "").strip()
        if resolved:
            return resolved.rstrip("/")
    except Exception:
        logger.debug("Ollama base-url resolution failed; using default", exc_info=True)
    host = str(os.environ.get("OLLAMA_HOST") or "").strip()
    if not host:
        return "http://localhost:11434"
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


def _cloud_api_key(explicit: str | None = None) -> str:
    """The Ollama Cloud key: caller's value, then env, then the
    credential ARES already reads for the cloud catalogue."""
    key = str(explicit or "").strip()
    if key:
        return key
    key = str(os.environ.get("OLLAMA_API_KEY") or "").strip()
    if key:
        return key
    try:
        from api.model_catalog import _read_jaeger_credential

        return str(_read_jaeger_credential("ollama_cloud_api_key") or "").strip()
    except Exception:
        logger.debug("Ollama cloud credential lookup failed", exc_info=True)
        return ""


def _context_length_from_payload(payload: object) -> int:
    """Pull the window out of an ``/api/show`` body.

    The real value lives under an architecture-prefixed key
    (``deepseek4.context_length``, ``glm5.2.context_length``), so match
    on the suffix rather than enumerating architectures. ``details`` and
    a bare top-level key are checked too — older daemons and the
    ``/api/tags`` rows use those shapes.
    """
    if not isinstance(payload, dict):
        return 0
    model_info = payload.get("model_info")
    if isinstance(model_info, dict):
        for key, value in model_info.items():
            if str(key).endswith(".context_length") or key == "context_length":
                try:
                    resolved = int(value)
                except (TypeError, ValueError):
                    continue
                if resolved > 0:
                    return resolved
    details = payload.get("details")
    if isinstance(details, dict):
        try:
            resolved = int(details.get("context_length") or 0)
        except (TypeError, ValueError):
            resolved = 0
        if resolved > 0:
            return resolved
    try:
        resolved = int(payload.get("context_length") or 0)
    except (TypeError, ValueError):
        resolved = 0
    return resolved if resolved > 0 else 0


def _post_show(base: str, model: str, *, timeout: float, api_key: str = "") -> int:
    """One ``/api/show`` call. Returns 0 on any failure, including the
    provider answering with an ``error`` body (retired model, unknown
    id) — those are answers, not exceptions."""
    body = json.dumps({"model": model}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base}/api/show", data=body, headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        logger.debug("Ollama show probe failed for %s at %s", model, base, exc_info=True)
        return 0
    if isinstance(payload, dict) and payload.get("error"):
        logger.debug("Ollama show probe rejected %s: %s", model, payload["error"])
        return 0
    return _context_length_from_payload(payload)


def _local_name_variants(model: str) -> list[str]:
    """How a model id can be spelled to the LOCAL daemon.

    A pulled cloud model is tagged locally with a cloud marker, and the
    two forms differ by whether the id already carries a tag:
    ``glm-5.2`` is stored as ``glm-5.2:cloud``, while
    ``deepseek-v4-pro:0813`` becomes ``deepseek-v4-pro:0813-cloud``.
    """
    variants = [model]
    if not model.endswith("-cloud") and not model.endswith(":cloud"):
        variants.append(f"{model}-cloud" if ":" in model else f"{model}:cloud")
    return variants


def _cloud_name_variants(model: str) -> list[str]:
    """How a model id can be spelled to ollama.com — the cloud registry
    knows the plain id, not the local cloud tag."""
    variants = [model]
    for marker in ("-cloud", ":cloud"):
        if model.endswith(marker):
            variants.append(model[: -len(marker)])
    return variants


def installed_context_lengths() -> dict[str, int]:
    """``{model_name: window}`` for everything ``/api/tags`` lists.

    One request covers every pulled model, cloud ones included (they come
    back with a ``remote_host``), which makes this the cheap way to stamp
    real windows onto a catalogue instead of probing per model.
    """
    request = urllib.request.Request(f"{_local_base_url()}/api/tags")
    try:
        with urllib.request.urlopen(request, timeout=_LOCAL_TIMEOUT) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        logger.debug("Ollama tags probe failed", exc_info=True)
        return {}
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return {}
    out: dict[str, int] = {}
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        window = _context_length_from_payload(entry)
        if name and window > 0:
            out[name] = window
    return out


def context_length(
    model: str,
    *,
    provider: str | None = None,
    api_key: str | None = None,
    allow_cloud: bool = True,
) -> int:
    """The model's real context window, or 0 when the provider won't say.

    ``provider`` only decides which endpoint is tried first: a
    ``*-cloud`` provider goes straight to ollama.com, since the local
    daemon usually has never heard of the id. Everything else tries
    local first and only phones out if that misses.

    ``allow_cloud=False`` keeps the probe entirely on-device — for
    callers that must not make an outbound request.
    """
    name = str(model or "").strip()
    if not name:
        return 0

    cache_key = f"{provider or ''}|{name}|{int(allow_cloud)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    provider_id = str(provider or "").strip().lower()
    prefer_cloud = "cloud" in provider_id

    def _try_local() -> int:
        base = _local_base_url()
        installed = installed_context_lengths()
        for candidate in _local_name_variants(name):
            if installed.get(candidate, 0) > 0:
                return installed[candidate]
        for candidate in _local_name_variants(name):
            window = _post_show(base, candidate, timeout=_LOCAL_TIMEOUT)
            if window > 0:
                return window
        return 0

    def _try_cloud() -> int:
        if not allow_cloud:
            return 0
        key = _cloud_api_key(api_key)
        if not key:
            return 0
        for candidate in _cloud_name_variants(name):
            window = _post_show(
                CLOUD_API_BASE, candidate, timeout=_CLOUD_TIMEOUT, api_key=key,
            )
            if window > 0:
                return window
        return 0

    order = (_try_cloud, _try_local) if prefer_cloud else (_try_local, _try_cloud)
    window = 0
    for attempt in order:
        window = attempt()
        if window > 0:
            break

    _cache_put(cache_key, window)
    if window > 0:
        logger.debug("Ollama reports context_length=%s for %s", window, name)
    return window


__all__ = [
    "context_length",
    "installed_context_lengths",
    "reset_cache",
]
