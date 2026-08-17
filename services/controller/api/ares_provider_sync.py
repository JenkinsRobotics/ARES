"""Synchronize ARES model selection with the Jaeger runtime contract.

ARES writes only its own profile configuration. Jaeger selections are sent to
Jaeger's validated bridge command; this module never opens Jaeger config or
credential files.
"""

from __future__ import annotations

import logging
import os
import shutil
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import yaml

from api.providers.jaeger.paths import expand_path

logger = logging.getLogger(__name__)


PROVIDER_PRESETS: dict[str, dict[str, str | None]] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_key_env": "GOOGLE_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
    },
    "ollama-cloud": {
        "base_url": "https://ollama.com/v1",
        "api_key_env": "OLLAMA_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434",
        "api_key_env": None,
    },
    "ollama-launch": {
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key_env": None,
    },
    "lmstudio": {
        "base_url": "http://localhost:1234/v1",
        "api_key_env": None,
    },
    "local": {
        "base_url": None,
        "api_key_env": None,
    },
}

JaegerAI_FALLBACK_PROVIDER_MAP: dict[str, str | None] = {
    "anthropic": "anthropic",
    "gemini": "gemini",
    "lmstudio": "lmstudio",
    "local": "local",
    "ollama": "ollama",
    "ollama-launch": "ollama",
    "ollama-cloud": "ollama-cloud",
    "ollama-local": "ollama",
    "openai": "openai",
    "xai": "xai",
    # Ares OAuth provider slugs are not runnable by JaegerAI today unless mapped.
    "openai-codex": None,
    "xai-oauth": "xai",
}

def provider_runtime_status(provider: str, base_url: str | None = None) -> dict[str, Any]:
    """Report provider runtime readiness without mutating configuration."""
    normalized = str(provider or "").strip().lower()
    if normalized in {"ollama", "ollama-launch", "ollama-local", "local"}:
        endpoint = str(base_url or PROVIDER_PRESETS["ollama"]["base_url"] or "").strip().rstrip("/")
        api_root = endpoint[:-3] if endpoint.endswith("/v1") else endpoint
        installed = bool(shutil.which("ollama")) or any(
            path.exists()
            for path in (
                Path("/Applications/Ollama.app"),
                Path.home() / "Applications" / "Ollama.app",
            )
        )
        try:
            with urllib.request.urlopen(f"{api_root}/api/tags", timeout=1.5) as response:
                payload = yaml.safe_load(response.read().decode("utf-8")) or {}
            models = payload.get("models") if isinstance(payload, dict) else []
            return {
                "provider": normalized,
                "available": True,
                "state": "running",
                "installed": installed,
                "model_count": len(models) if isinstance(models, list) else 0,
                "base_url": endpoint,
            }
        except Exception:
            return {
                "provider": normalized,
                "available": False,
                "state": "installed_not_running" if installed else "not_installed",
                "installed": installed,
                "model_count": 0,
                "base_url": endpoint,
            }
    if normalized == "ollama-cloud":
        try:
            from api.provider_credentials import provider_has_usable_credential

            configured = bool(provider_has_usable_credential("ollama-cloud"))
        except Exception:
            configured = bool(os.getenv("OLLAMA_API_KEY", "").strip())
        return {
            "provider": normalized,
            "available": configured,
            "state": "configured" if configured else "missing_credentials",
            "installed": True,
            "model_count": None,
            "base_url": str(base_url or PROVIDER_PRESETS[normalized]["base_url"] or "").strip(),
        }
    return {
        "provider": normalized,
        "available": True,
        "state": "configured",
        "installed": True,
        "model_count": None,
        "base_url": str(base_url or "").strip() or None,
    }


def load_yaml_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    config_path = Path(path).expanduser()
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def save_yaml_config(path: str | os.PathLike[str], data: dict[str, Any]) -> None:
    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _normalize_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized not in PROVIDER_PRESETS:
        supported = ", ".join(sorted(PROVIDER_PRESETS))
        raise ValueError(f"Unsupported provider: {provider}. Supported providers: {supported}")
    return normalized


def _normalize_targets(targets: Iterable[str] | None) -> list[str]:
    requested = list(targets or ["ares", "jaeger"])
    normalized: list[str] = []
    for target in requested:
        value = str(target or "").strip().lower()
        if value not in {"ares", "jaeger"}:
            raise ValueError(f"Unsupported sync target: {target}. Supported targets: ares, jaeger")
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError("At least one sync target is required")
    return normalized


def _resolved_provider_values(provider: str, base_url: str | None, api_key_env: str | None) -> tuple[str | None, str | None]:
    preset = PROVIDER_PRESETS[provider]
    resolved_base_url = str(base_url).strip() if base_url else preset.get("base_url")
    resolved_api_key_env = str(api_key_env).strip() if api_key_env else preset.get("api_key_env")
    return resolved_base_url or None, resolved_api_key_env or None


def _sync_ares_config(config: dict[str, Any], provider: str, model: str, base_url: str | None) -> dict[str, Any]:
    updated = deepcopy(config)
    model_config = updated.get("model")
    if not isinstance(model_config, dict):
        model_config = {}
        updated["model"] = model_config
    model_config["provider"] = provider
    model_config["default"] = model
    if base_url:
        model_config["base_url"] = base_url
    else:
        model_config.pop("base_url", None)
    return updated


def _path_result(path: Path, changed: bool) -> dict[str, Any]:
    return {"path": str(path), "changed": changed}


def _jaeger_supported_fallback_chain(
    fallback_chain: list[Any],
    jaeger_current: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Translate Ares fallback entries into JaegerAI-runnable provider entries."""
    external_model = jaeger_current.get("external_model") if isinstance(jaeger_current, dict) else None
    active_identity: tuple[str, str] | None = None
    if isinstance(external_model, dict) and external_model.get("enabled"):
        active_provider = str(external_model.get("provider") or "").strip().lower()
        active_model = str(external_model.get("model") or "").strip().lower()
        if active_provider and active_model:
            active_identity = (active_provider, active_model)

    translated: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for raw_entry in fallback_chain:
        if not isinstance(raw_entry, dict):
            skipped.append({"provider": "", "model": "", "reason": "entry is not an object"})
            continue
        provider = str(raw_entry.get("provider") or "").strip().lower()
        model = str(raw_entry.get("model") or "").strip()
        if not provider or not model:
            skipped.append({"provider": provider, "model": model, "reason": "missing provider or model"})
            continue

        mapped_provider = JaegerAI_FALLBACK_PROVIDER_MAP.get(provider)
        if not mapped_provider:
            skipped.append({
                "provider": provider,
                "model": model,
                "reason": "provider is not supported by JaegerAI fallback runtime",
            })
            continue

        identity = (mapped_provider.lower(), model.lower())
        if active_identity is not None and identity == active_identity:
            skipped.append({"provider": provider, "model": model, "reason": "same as active JaegerAI external_model"})
            continue
        if identity in seen:
            skipped.append({"provider": provider, "model": model, "reason": "duplicate fallback route"})
            continue

        seen.add(identity)
        entry = deepcopy(raw_entry)
        entry["provider"] = mapped_provider
        translated.append(entry)

    return translated, skipped


def sync_provider(
    provider: str,
    model: str,
    base_url: str | None = None,
    targets: Iterable[str] | None = None,
    api_key_env: str | None = None,
    ares_config_path: str | os.PathLike[str] | None = None,
    jaeger_config_path: str | os.PathLike[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync provider settings to requested config targets.

    Returns a JSON-safe dictionary. The function never writes API key values;
    callers should instruct users to set the returned env var themselves.
    """
    normalized_provider = _normalize_provider(provider)
    normalized_model = str(model or "").strip()
    if not normalized_model:
        raise ValueError("model is required")
    normalized_targets = _normalize_targets(targets)
    resolved_base_url, resolved_api_key_env = _resolved_provider_values(normalized_provider, base_url, api_key_env)

    results: dict[str, Any] = {
        "ok": True,
        "provider": normalized_provider,
        "model": normalized_model,
        "base_url": resolved_base_url,
        "api_key_env": resolved_api_key_env,
        "required_env": [resolved_api_key_env] if resolved_api_key_env else [],
        "targets": {},
        "changed_targets": [],
        "dry_run": bool(dry_run),
        "secret_values_written": False,
        "fallback_chain_synced": False,
    }

    if "ares" in normalized_targets:
        if ares_config_path is None:
            raise ValueError("ares_config_path is required when syncing Ares")
        path = expand_path(ares_config_path)
        current = load_yaml_config(path)
        updated = _sync_ares_config(current, normalized_provider, normalized_model, resolved_base_url)
        changed = updated != current
        if changed and not dry_run:
            save_yaml_config(path, updated)
        results["targets"]["ares"] = _path_result(path, changed)
        if changed:
            results["changed_targets"].append("ares")

    if "jaeger" in normalized_targets:
        if jaeger_config_path is not None:
            raise ValueError(
                "jaeger_config_path is no longer supported; Jaeger owns its configuration")
        jaeger_provider = JaegerAI_FALLBACK_PROVIDER_MAP.get(normalized_provider, normalized_provider)
        if not jaeger_provider:
            raise ValueError(f"Provider {normalized_provider} is not supported by JaegerAI")
        try:
            from api.model_context import resolve_context_length_for_session_model

            context_length = resolve_context_length_for_session_model(
                normalized_model, normalized_provider, base_url=resolved_base_url)
        except Exception:
            context_length = 0
        from api.providers.jaeger.streaming import command_local_companion

        runtime_result = command_local_companion("configure_model", {
            "provider": jaeger_provider,
            "model": normalized_model,
            "base_url": resolved_base_url,
            "context_length": context_length or None,
            "dry_run": bool(dry_run),
        })
        if not isinstance(runtime_result, dict):
            raise RuntimeError("Jaeger returned an invalid model configuration result")
        changed = bool(runtime_result.get("changed"))
        results["targets"]["jaeger"] = {
            "owner": "jaeger",
            "changed": changed,
            "restart_required": bool(runtime_result.get("restart_required")),
        }
        if changed:
            results["changed_targets"].append("jaeger")
        if changed and not dry_run:
            from api.providers.jaeger.streaming import reset_jaeger_runtime

            reset_jaeger_runtime()

    return results


def sync_fallback_chain(
    ares_config_path: str | os.PathLike[str] | None = None,
    jaeger_config_path: str | os.PathLike[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync the fallback_providers chain from Ares config to JaegerAI config.
    
    Returns a JSON-safe dictionary describing what was synced.
    """
    results: dict[str, Any] = {
        "ok": True,
        "fallback_chain_synced": False,
        "dry_run": bool(dry_run),
        "targets": {},
        "changed_targets": [],
        "fallback_entries_synced": 0,
    }
    
    if ares_config_path is None:
        raise ValueError("ares_config_path is required")
    
    ares_path = expand_path(ares_config_path)
    ares_current = load_yaml_config(ares_path)
    fallback_chain = ares_current.get("fallback_providers", [])
    
    if not isinstance(fallback_chain, list) or not fallback_chain:
        results["targets"]["ares"] = {"path": str(ares_path), "changed": False, "note": "no fallback chain"}
        return results
    
    results["targets"]["ares"] = {
        "path": str(ares_path),
        "changed": False,
        "fallback_entries": len(fallback_chain),
    }
    
    if jaeger_config_path is not None:
        raise ValueError(
            "jaeger_config_path is no longer supported; Jaeger owns its configuration")
    _translated, skipped_entries = _jaeger_supported_fallback_chain(fallback_chain, {})
    results["targets"]["jaeger"] = {
        "owner": "jaeger",
        "changed": False,
        "supported": False,
        "note": "Jaeger does not advertise a fallback-chain configuration contract",
        "skipped_entries": skipped_entries,
    }

    return results
