"""ARES model-catalog presentation and cross-runtime selection synchronization."""

from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

JaegerAI_COMPATIBLE_MODEL_PROVIDERS = frozenset(
    {
        "anthropic",
        "gemini",
        "lmstudio",
        "local",
        "ollama",
        "ollama-cloud",
        "ollama-local",
        "openai",
        "xai",
    }
)

XAI_CURATED_MODELS = (
    {"id": "grok-4.6", "label": "grok-4.6"},
    {"id": "grok-4.5", "label": "grok-4.5"},
    {"id": "grok-3", "label": "grok-3"},
    {"id": "grok-2", "label": "grok-2"},
)

OPENAI_CURATED_MODELS = (
    {"id": "gpt-4o", "label": "gpt-4o"},
    {"id": "gpt-4o-mini", "label": "gpt-4o-mini"},
    {"id": "o3-mini", "label": "o3-mini"},
    {"id": "o1", "label": "o1"},
    {"id": "gpt-4.5-preview", "label": "gpt-4.5-preview"},
)

ANTHROPIC_CURATED_MODELS = (
    {"id": "claude-3-5-sonnet-20241022", "label": "Claude 3.5 Sonnet"},
    {"id": "claude-3-5-haiku-20241022", "label": "Claude 3.5 Haiku"},
    {"id": "claude-opus-4-7", "label": "Claude Opus 4.7"},
    {"id": "claude-3-opus-20240229", "label": "Claude 3 Opus"},
)

GEMINI_CURATED_MODELS = (
    {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
    {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
    {"id": "gemini-1.5-pro", "label": "Gemini 1.5 Pro"},
)


def _fetch_ollama_local_models() -> list[dict]:
    """Fetch available models from the local Ollama server."""
    import json
    import urllib.request
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read())
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            if not name:
                continue
            details = m.get("details", {})
            caps = m.get("capabilities", [])
            if caps and all(c == "embedding" for c in caps):
                continue
            models.append({
                "id": name,
                "label": name,
                "provider": "ollama",
                "provider_id": "ollama",
                "location": "local",
                "context_length": details.get("context_length", 0),
                "capabilities": caps,
            })
        # ``/api/tags`` reports a window for GGUF models but leaves it null
        # for MLX ones, so probe whatever came back empty.
        return _stamp_ollama_context_lengths(models)
    except Exception:
        return []


def _stamp_ollama_context_lengths(models: list[dict], api_key: str | None = None) -> list[dict]:
    """Fill in each entry's real ``context_length`` from Ollama.

    ``/v1/models`` — the OpenAI-compatible listing this catalogue is built
    from — carries no window, so without this every cloud model reached
    the resolver with nothing and fell back to a keyword guess (anything
    matching "deepseek" → 131072, when ``deepseek-v4-pro:0813`` is really
    1048576). ``/api/show`` does publish it, so ask.

    Probed concurrently because a cloud listing is ~20 models and each
    probe is a round trip; the probe layer caches per model id, so this
    costs one burst per catalogue rebuild rather than one call per model
    per request. Any model that won't answer keeps whatever it had —
    a missing window is the resolver's problem to fall back on, not a
    reason to fail the catalogue.
    """
    if not models:
        return models
    try:
        from concurrent.futures import ThreadPoolExecutor

        from api.providers.ollama.context_probe import context_length
    except Exception:
        return models

    pending = [m for m in models if not m.get("context_length")]
    if not pending:
        return models

    def _probe(entry: dict) -> tuple[dict, int]:
        try:
            return entry, context_length(
                str(entry.get("id") or ""),
                provider=str(entry.get("provider_id") or entry.get("provider") or ""),
                api_key=api_key,
            )
        except Exception:
            return entry, 0

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for entry, window in pool.map(_probe, pending):
                if window > 0:
                    entry["context_length"] = window
    except Exception:
        logger.debug("Ollama context-length stamping failed", exc_info=True)
    return models


def _ollama_cloud_models() -> list[dict]:
    """Curated catalog; ARES never receives Jaeger's raw provider secret."""
    return [
        {"id": "qwen3.5:397b", "label": "qwen3.5:397b", "provider": "ollama-cloud", "provider_id": "ollama-cloud", "location": "cloud", "context_length": 131072},
        {"id": "glm-5.1", "label": "glm-5.1", "provider": "ollama-cloud", "provider_id": "ollama-cloud", "location": "cloud", "context_length": 131072},
        {"id": "kimi-k2.7-code", "label": "kimi-k2.7-code", "provider": "ollama-cloud", "provider_id": "ollama-cloud", "location": "cloud", "context_length": 262144},
        {"id": "deepseek-v4-pro:0813", "label": "deepseek-v4-pro:0813", "provider": "ollama-cloud", "provider_id": "ollama-cloud", "location": "cloud", "context_length": 131072},
        {"id": "gemma4:31b", "label": "gemma4:31b", "provider": "ollama-cloud", "provider_id": "ollama-cloud", "location": "cloud", "context_length": 131072},
    ]


def _jaeger_credential_names() -> set[str]:
    """Return names only through Jaeger's credential bridge contract."""
    try:
        from api.runtime_credentials import list_runtime_credentials

        return list_runtime_credentials()
    except Exception:
        logger.debug("Jaeger credential inventory unavailable", exc_info=True)
        return set()


def _xai_models() -> list[dict]:
    """Curated catalog; live authentication remains inside Jaeger."""
    return [
        {
            "id": m["id"],
            "label": m["label"],
            "provider": "xai",
            "provider_id": "xai",
            "location": "cloud",
        }
        for m in XAI_CURATED_MODELS
    ]


def _get_jaeger_local_models() -> list[dict]:
    """Discover installed local MLX / GGUF models for Jaeger."""
    try:
        from api.backends.model_discovery import list_jaeger_installed_gguf
        installed = list_jaeger_installed_gguf()
    except Exception:
        installed = []
    models = []
    seen = set()
    for m in installed:
        mid = m.get("id")
        if not mid or mid in seen:
            continue
        seen.add(mid)
        models.append({
            "id": mid,
            "label": m.get("label") or mid,
            "provider": "local",
            "provider_id": "local",
            "location": "local",
        })
    return models


def _configured_model_badges(
    groups: list[dict[str, Any]],
    default_model: str,
    active_provider: str,
) -> dict[str, Any]:
    """Badge the models that are actually *configured*, not the whole catalog.

    A badge means "this model is your current selection", which is why the
    picker hoists badged models into a "Configured" section above the provider
    groups and ranks them by ``role``.

    Badging every model in every group (the previous behavior) made that
    section swallow the entire catalog: the picker's provider groups were left
    empty, so none of their collapsible headings rendered and the whole list
    flattened into one alphabetical run of every model from every provider.
    Only the active selection earns a badge, so the "Configured" section stays
    the short list of things the user actually chose.

    Returned entries carry an explicit ``role`` so the client can distinguish a
    real selection from bare provider metadata.
    """
    wanted_model = str(default_model or "").strip()
    if not wanted_model:
        return {}
    wanted_provider = str(active_provider or "").strip().lower()

    badges: dict[str, Any] = {}
    for group in groups:
        pid = str(group.get("provider_id") or group.get("provider") or "").strip().lower()
        if wanted_provider and pid != wanted_provider:
            continue
        for key in ("models", "extra_models"):
            for model in group.get(key) or []:
                mid = str((model or {}).get("id") or "").strip()
                if mid and mid == wanted_model:
                    badges[mid] = {"provider": pid, "role": "primary", "label": "Primary"}
    return badges


def active_profile_config_path() -> Path:
    try:
        from api.profiles import get_active_ares_home

        return Path(get_active_ares_home()) / "config.yaml"
    except Exception:
        from api.config import _get_config_path

        return _get_config_path()


def sync_main_model_to_jaeger(result: dict) -> None:
    provider = str((result or {}).get("provider") or "").strip().lower()
    model = str((result or {}).get("model") or "").strip()
    if not provider or not model:
        return
    try:
        from api.ares_provider_sync import JaegerAI_FALLBACK_PROVIDER_MAP, sync_provider

        mapped = JaegerAI_FALLBACK_PROVIDER_MAP.get(provider)
        if not mapped:
            return
        sync_provider(
            provider=mapped,
            model=model,
            targets=["jaeger"],
            ares_config_path=active_profile_config_path(),
        )
        from api.providers.jaeger.streaming import reset_jaeger_runtime

        reset_jaeger_runtime()
    except Exception:
        logger.warning("Failed to synchronize the main model with JaegerAI", exc_info=True)


def filter_catalog_for_active_backend(catalog: dict, *, enrich: bool = True) -> dict:
    try:
        from api.backend_selector import BACKEND_JAEGER, get_active_backend
        from api.config import get_config

        if get_active_backend(get_config()) != BACKEND_JAEGER:
            return catalog
    except Exception:
        return catalog

    filtered = copy.deepcopy(catalog or {})
    existing_groups = list(filtered.get("groups") or [])
    groups: list[dict[str, Any]] = [
        group
        for group in existing_groups
        if str(group.get("provider_id") or group.get("provider") or "").strip().lower()
        in JaegerAI_COMPATIBLE_MODEL_PROVIDERS
    ]

    existing_pids = {
        str(g.get("provider_id") or g.get("provider") or "").strip().lower()
        for g in groups
    }

    if not enrich:
        filtered["groups"] = groups
        filtered["ares_backend"] = BACKEND_JAEGER
        filtered["compatible_providers"] = sorted(JaegerAI_COMPATIBLE_MODEL_PROVIDERS)

        active_provider = str(filtered.get("active_provider") or "").strip().lower()
        if not active_provider or active_provider not in existing_pids:
            first = groups[0] if groups else {}
            filtered["active_provider"] = first.get("provider_id") or first.get("provider") or None

        default_model = str(filtered.get("default_model") or "").strip()
        default_present = any(
            (model or {}).get("id") == default_model
            for group in groups
            for key in ("models", "extra_models")
            for model in (group.get(key) or [])
        )
        if not default_present:
            filtered["default_model"] = next(
                (
                    (models[0] or {}).get("id")
                    for group in groups
                    if (models := (group.get("models") or group.get("extra_models") or []))
                ),
                None,
            )

        # Built after the selection is resolved, so the badge marks the model
        # the catalog actually reports as active rather than a stale input.
        filtered["configured_model_badges"] = _configured_model_badges(
            groups,
            str(filtered.get("default_model") or ""),
            str(filtered.get("active_provider") or ""),
        )
        return filtered

    # Discover live and installed Jaeger models
    try:
        from api.backends.model_discovery import discover_jaeger_models
        discovered = discover_jaeger_models()
    except Exception:
        discovered = {}

    default_info = discovered.get("default") or {}
    configured_default_model = str(default_info.get("model") or "").strip()
    configured_default_provider = str(default_info.get("provider") or "").strip().lower()
    credential_names = _jaeger_credential_names()

    # Append xAI if configured
    if "xai_api_key" in credential_names and "xai" not in existing_pids:
        xai_models = _xai_models()
        if xai_models:
            groups.append({
                "provider": "xAI (Grok)",
                "provider_id": "xai",
                "label": "xAI (Grok)",
                "models": xai_models,
            })
            existing_pids.add("xai")

    # Append Ollama Cloud if configured
    if "ollama_cloud_api_key" in credential_names and "ollama-cloud" not in existing_pids:
        cloud_models = _ollama_cloud_models()
        if cloud_models:
            groups.append({
                "provider": "Ollama Cloud",
                "provider_id": "ollama-cloud",
                "label": "Ollama Cloud",
                "models": cloud_models,
            })
            existing_pids.add("ollama-cloud")

    # Append local Ollama daemon if running
    if "ollama" not in existing_pids:
        ollama_local = _fetch_ollama_local_models()
        if ollama_local:
            groups.append({
                "provider": "Ollama (Local)",
                "provider_id": "ollama",
                "label": "Ollama (Local)",
                "models": ollama_local,
            })
            existing_pids.add("ollama")

    # Append local MLX / GGUF models
    if "local" not in existing_pids:
        local_models = _get_jaeger_local_models()
        if local_models:
            groups.append({
                "provider": "Local (Jaeger AI / MLX / GGUF)",
                "provider_id": "local",
                "label": "Local (Jaeger AI / MLX / GGUF)",
                "models": local_models,
            })
            existing_pids.add("local")

    # Append OpenAI if configured
    if "openai_api_key" in credential_names and "openai" not in existing_pids:
        groups.append({
            "provider": "OpenAI",
            "provider_id": "openai",
            "label": "OpenAI",
            "models": [
                {
                    "id": m["id"],
                    "label": m["label"],
                    "provider": "openai",
                    "provider_id": "openai",
                    "location": "cloud",
                }
                for m in OPENAI_CURATED_MODELS
            ],
        })
        existing_pids.add("openai")

    # Append Anthropic if configured
    if "anthropic_api_key" in credential_names and "anthropic" not in existing_pids:
        groups.append({
            "provider": "Anthropic",
            "provider_id": "anthropic",
            "label": "Anthropic",
            "models": [
                {
                    "id": m["id"],
                    "label": m["label"],
                    "provider": "anthropic",
                    "provider_id": "anthropic",
                    "location": "cloud",
                }
                for m in ANTHROPIC_CURATED_MODELS
            ],
        })
        existing_pids.add("anthropic")

    # Append Gemini if configured
    if "gemini_api_key" in credential_names and "gemini" not in existing_pids:
        groups.append({
            "provider": "Google Gemini",
            "provider_id": "gemini",
            "label": "Google Gemini",
            "models": [
                {
                    "id": m["id"],
                    "label": m["label"],
                    "provider": "gemini",
                    "provider_id": "gemini",
                    "location": "cloud",
                }
                for m in GEMINI_CURATED_MODELS
            ],
        })
        existing_pids.add("gemini")

    filtered["groups"] = groups
    filtered["ares_backend"] = BACKEND_JAEGER
    filtered["compatible_providers"] = sorted(JaegerAI_COMPATIBLE_MODEL_PROVIDERS)

    # Resolve active provider & default model
    active_provider = str(filtered.get("active_provider") or "").strip().lower()
    if not active_provider or active_provider not in existing_pids:
        if configured_default_provider and configured_default_provider in existing_pids:
            filtered["active_provider"] = configured_default_provider
        else:
            first = groups[0] if groups else {}
            filtered["active_provider"] = first.get("provider_id") or first.get("provider") or None

    default_model = str(filtered.get("default_model") or "").strip()
    default_present = any(
        (model or {}).get("id") == default_model
        for group in groups
        for key in ("models", "extra_models")
        for model in (group.get(key) or [])
    )
    if not default_present:
        if configured_default_model and any(
            (model or {}).get("id") == configured_default_model
            for group in groups
            for key in ("models", "extra_models")
            for model in (group.get(key) or [])
        ):
            filtered["default_model"] = configured_default_model
        else:
            filtered["default_model"] = next(
                (
                    (models[0] or {}).get("id")
                    for group in groups
                    if (models := (group.get("models") or group.get("extra_models") or []))
                ),
                None,
            )

    # Built after the selection is resolved, so the badge marks the model the
    # catalog actually reports as active rather than a stale input.
    filtered["configured_model_badges"] = _configured_model_badges(
        groups,
        str(filtered.get("default_model") or ""),
        str(filtered.get("active_provider") or ""),
    )

    return filtered
