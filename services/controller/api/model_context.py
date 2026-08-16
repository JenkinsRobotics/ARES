"""Provider normalization and context-window lookup shared by HTTP and workers."""

from __future__ import annotations

import logging
import os
import re


logger = logging.getLogger(__name__)

_PROVIDER_ALIASES = {
    "claude": "anthropic",
    "gpt": "openai",
    "gemini": "google",
    "openai-codex": "openai",
    "openai-api": "openai",
    "google-gemini": "google",
    "google-ai-studio": "google",
    "claude-code": "anthropic",
}


def _starts_token(raw: str, prefix: str) -> bool:
    if not raw.startswith(prefix):
        return False
    rest = raw[len(prefix):]
    return rest == "" or rest[0] in ":/"


def normalize_provider_id(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[raw]
    for prefix, normalized in (
        ("openai-codex", "openai"),
        ("openai", "openai"),
        ("anthropic", "anthropic"),
        ("claude", "anthropic"),
        ("google", "google"),
        ("gemini", "google"),
        ("openrouter", "openrouter"),
        ("custom", "custom"),
    ):
        if _starts_token(raw, prefix):
            return normalized
    return ""


def catalog_has_provider(
    provider_raw: str,
    provider_normalized: str,
    raw_provider_ids: set[str],
    normalized_provider_ids: set[str],
) -> bool:
    return bool(
        provider_raw in raw_provider_ids
        or (provider_normalized and provider_normalized in raw_provider_ids)
        or (provider_normalized and provider_normalized in normalized_provider_ids)
    )


_catalog_has_provider = catalog_has_provider


def _clean_provider(value: str | None) -> str | None:
    provider = str(value or "").strip().lower()
    if not provider or provider == "default":
        return None
    return provider.removeprefix("@") or None


def _split_qualified_model(model: str) -> tuple[str, str | None]:
    value = str(model or "").strip()
    if value.startswith("@") and ":" in value:
        provider, bare = value[1:].rsplit(":", 1)
        cleaned = _clean_provider(provider)
        if cleaned and bare.strip():
            return bare.strip(), cleaned
    return value, None


def _canonical_provider(value: str | None) -> str:
    provider = _clean_provider(value) or ""
    if not provider:
        return ""
    try:
        from api.config import _resolve_provider_alias

        provider = _resolve_provider_alias(provider)
    except Exception:
        pass
    return str(provider or "").strip().lower()


def _model_candidates(model: object) -> tuple[str, ...]:
    raw = str(model or "").strip()
    candidates: list[str] = []
    for candidate in (raw, _split_qualified_model(raw)[0]):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
        if "/" in candidate:
            bare = candidate.split("/", 1)[1].strip()
            if bare and bare not in candidates:
                candidates.append(bare)
    return tuple(candidates)


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _models_context_length(models: object, model: str) -> int | None:
    candidates = _model_candidates(model)
    if isinstance(models, dict):
        for candidate in candidates:
            entry = models.get(candidate)
            value = entry.get("context_length") if isinstance(entry, dict) else entry
            result = _positive_int(value)
            if result is not None:
                return result
    if isinstance(models, list):
        for entry in models:
            if not isinstance(entry, dict):
                continue
            entry_model = str(entry.get("id") or entry.get("model") or entry.get("name") or "").strip()
            if entry_model in candidates:
                result = _positive_int(entry.get("context_length"))
                if result is not None:
                    return result
    return None


def _providers_match(config_key: object, provider: str) -> bool:
    if not provider:
        return False
    raw = str(config_key or "").strip().lower()
    return bool(
        raw == provider
        or _canonical_provider(raw) == _canonical_provider(provider)
    )


def _custom_slug(name: object) -> str:
    try:
        from api.config import _custom_provider_slug_from_name

        return _custom_provider_slug_from_name(name)
    except Exception:
        raw = str(name or "").strip().lower()
        if raw.startswith("custom:"):
            return raw
        slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9._-]+", "-", raw)).strip("-")
        return f"custom:{slug}" if slug else ""


def _resolve_key(raw_api_key: object, raw_key_env: object = None) -> str:
    text = str(raw_api_key or "").strip()
    if text.startswith("${") and text.endswith("}") and len(text) > 3:
        environment_name = text[2:-1]
        resolved = os.getenv(environment_name, "").strip()
        if resolved:
            return resolved
        logger.debug("Custom provider API key template %s is unset or empty", text)
        text = ""
    if text:
        return text
    return os.getenv(str(raw_key_env or "").strip(), "").strip() if raw_key_env else ""


def _custom_key(entry: dict, provider: str) -> str:
    resolved = _resolve_key(entry.get("api_key"), entry.get("key_env"))
    if resolved:
        return resolved
    try:
        from api.config import _lookup_custom_api_key_env

        return _lookup_custom_api_key_env(provider) or ""
    except Exception:
        return ""


def _config_key(provider: str, cfg: dict) -> str:
    providers = cfg.get("providers") or {}
    if isinstance(providers, dict):
        for key, entry in providers.items():
            if isinstance(entry, dict) and _providers_match(key, provider):
                resolved = _resolve_key(entry.get("api_key"), entry.get("key_env"))
                if resolved:
                    return resolved
    model_cfg = cfg.get("model") or {}
    if isinstance(model_cfg, dict):
        configured = _canonical_provider(model_cfg.get("provider"))
        if not provider or _providers_match(configured, provider):
            return _resolve_key(model_cfg.get("api_key"), model_cfg.get("key_env"))
    return ""


def _matches_default(model: str, default: str, provider: str) -> bool:
    if not model or not default:
        return False
    if model == default:
        return True

    def split(value: str) -> tuple[str, str | None]:
        bare, explicit = _split_qualified_model(value)
        if explicit:
            return bare, explicit
        if "/" in value:
            prefix, rest = value.split("/", 1)
            return rest.strip(), prefix.strip().lower() or None
        return value, None

    model_bare, model_provider = split(model)
    default_bare, default_provider = split(default)
    model_provider = model_provider or provider or None
    return bool(
        model_bare
        and model_bare == default_bare
        and not (
            model_provider
            and default_provider
            and model_provider != default_provider
        )
    )


class ContextLengthLookupInputs:
    __slots__ = ("config_context_length", "custom_providers", "base_url", "provider", "api_key")

    def __init__(
        self,
        *,
        config_context_length: int | None = None,
        custom_providers: list | None = None,
        base_url: str = "",
        provider: str = "",
        api_key: str = "",
    ) -> None:
        self.config_context_length = config_context_length
        self.custom_providers = custom_providers
        self.base_url = base_url
        self.provider = provider
        self.api_key = api_key


def context_length_lookup_inputs_for_model(
    model: str | None,
    provider: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    cfg: dict | None = None,
) -> ContextLengthLookupInputs:
    model_value = str(model or "").strip()
    if not model_value:
        return ContextLengthLookupInputs()
    if cfg is None:
        try:
            from api.config import get_config

            cfg = get_config()
        except Exception:
            cfg = {}
    cfg = cfg if isinstance(cfg, dict) else {}
    bare, explicit_provider = _split_qualified_model(model_value)
    effective_provider = _canonical_provider(provider or explicit_provider)
    effective_base = str(base_url or "").strip()
    model_cfg = cfg.get("model") or {}
    if isinstance(model_cfg, dict):
        effective_provider = effective_provider or _canonical_provider(model_cfg.get("provider"))
        effective_base = effective_base or str(model_cfg.get("base_url") or "").strip()

    provider_context = None
    providers_cfg = cfg.get("providers") or {}
    if isinstance(providers_cfg, dict):
        for key, entry in providers_cfg.items():
            if not isinstance(entry, dict) or not _providers_match(key, effective_provider):
                continue
            effective_base = effective_base or str(entry.get("base_url") or "").strip()
            provider_context = _models_context_length(entry.get("models"), bare or model_value)
            break

    custom_providers = cfg.get("custom_providers")
    custom_providers = custom_providers if isinstance(custom_providers, list) else None
    custom_context = None
    effective_key = str(api_key or "").strip()
    if custom_providers:
        target_base = effective_base.rstrip("/")
        model_candidates = set(_model_candidates(bare or model_value))
        for entry in custom_providers:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            slug = _custom_slug(name)
            entry_base = str(entry.get("base_url") or "").strip()
            models = entry.get("models")
            model_match = bool(model_candidates.intersection(_model_candidates(entry.get("model"))))
            if isinstance(models, dict):
                model_match = model_match or any(candidate in models for candidate in model_candidates)
            provider_match = bool(
                effective_provider
                and (
                    effective_provider in {slug, name.lower()}
                    or (effective_provider == "custom" and len(custom_providers) == 1)
                )
            )
            base_match = bool(target_base and entry_base and target_base == entry_base.rstrip("/"))
            if not (provider_match or base_match or (not effective_provider and model_match)):
                continue
            effective_provider = effective_provider or slug
            effective_base = effective_base or entry_base
            effective_key = effective_key or _custom_key(entry, effective_provider or slug)
            custom_context = _models_context_length(models, bare or model_value)
            break

    global_context = None
    if isinstance(model_cfg, dict):
        default = str(model_cfg.get("default") or "").strip()
        raw_context = model_cfg.get("context_length")
        if raw_context is not None and (
            not default or _matches_default(model_value, default, effective_provider)
        ):
            global_context = _positive_int(raw_context)
    effective_key = effective_key or _config_key(effective_provider, cfg)
    return ContextLengthLookupInputs(
        config_context_length=provider_context or custom_context or global_context,
        custom_providers=custom_providers,
        base_url=effective_base,
        provider=effective_provider,
        api_key=effective_key,
    )


def should_accept_context_length_refresh(
    persisted: int,
    resolved: int,
    *,
    model_changed: bool = False,
) -> bool:
    if not resolved:
        return False
    if not persisted:
        return True
    return model_changed or not (resolved == 256_000 and persisted > resolved)


_JAEGER_WORKER_IDS = frozenset({"jaeger_local", "jaeger", "jros_local", "jros"})


def _ollama_probe_provider(provider: str | None) -> str | None:
    """Return the Ollama probe slug, or None if this is not an Ollama lane.

    ``normalize_provider_id`` is for first-party families (openai /
    anthropic / …). It has no ``ollama-cloud`` entry, so feeding it
    ``ollama-cloud`` used to collapse to ``""`` and then ``"ollama"`` —
    the session resolver (what the chat-tab context ring reads) asked
    the local daemon first and under-reported every hosted window.
    """
    raw = str(provider or "").strip().lower().replace("_", "-")
    if raw in {"ollama-cloud", "ollamacloud"}:
        return "ollama-cloud"
    if raw.startswith("ollama"):
        return "ollama"
    return None


def _jaeger_serving_window(model: str, api_key: str | None = None) -> int:
    """Window of the model Jaeger is actually serving, not the worker id.

    A session stored as ``jaeger_local`` / ``qwen3.5:397b`` is often an
    Ollama Cloud brain behind Jaeger. The worker slug is not a model
    family, so probing it as local Ollama is wrong. Prefer the ``ctx``
    already written onto Jaeger's serving lane, then probe that lane.
    """
    try:
        from api.providers.jaeger.active_model import active_model

        serving = active_model() or {}
    except Exception:
        logger.debug("Jaeger serving-model lookup failed", exc_info=True)
        serving = {}
    written = _positive_int(serving.get("ctx"))
    if written:
        return written
    serving_model = str(serving.get("model") or model or "").strip()
    serving_provider = str(serving.get("provider") or "").strip()
    if (
        serving_model
        and serving_provider
        and serving_provider.lower() not in _JAEGER_WORKER_IDS
    ):
        return _probe_provider_context_length(
            serving_model, serving_provider, api_key=api_key,
        )
    return 0


def _probe_provider_context_length(
    model: str,
    provider: str | None = None,
    *,
    api_key: str | None = None,
) -> int:
    """Ask the serving provider for the model's real window, or 0.

    Only providers that actually publish the number get probed. Ollama is
    the one that does — ``/api/show`` returns
    ``model_info["<arch>.context_length"]`` for local and cloud models
    alike, which is how ``deepseek-v4-pro:0813`` resolves to its real
    1048576 instead of the 131072 the keyword table returns for anything
    spelled "deepseek". OpenAI-compatible ``/v1/models`` responses carry
    no window at all, so there is nothing to ask those providers for.

    Never raises and never blocks a turn on a slow provider — the probe
    caches its own results, including misses.
    """
    raw = str(provider or "").strip().lower()
    if raw in _JAEGER_WORKER_IDS:
        return _jaeger_serving_window(model, api_key=api_key)

    provider_id = _ollama_probe_provider(provider)
    if not provider_id:
        # An unqualified model can still be an Ollama one; the local
        # daemon answers instantly when it is, and 0 when it is not.
        if raw:
            return 0
        provider_id = "ollama"
    try:
        from api.providers.ollama.context_probe import context_length

        return context_length(model, provider=provider_id, api_key=api_key)
    except Exception:
        logger.debug(
            "Provider context-length probe failed for %s (%s)",
            model,
            provider_id,
            exc_info=True,
        )
        return 0


def _estimate_model_context_length(model: str, provider: str | None = None) -> int:
    m = str(model or "").lower()
    p = str(provider or "").lower()
    if "qwen" in m:
        return 131_072
    if "kimi" in m:
        return 262_144
    if "glm" in m:
        return 131_072
    if "deepseek-v4" in m or "deepseek_v4" in m:
        return 1_048_576
    if "deepseek" in m:
        return 131_072
    if "gemma" in m:
        return 131_072
    if "grok" in m or p == "xai":
        return 131_072
    if "gemini" in m or p == "google" or p == "gemini":
        return 1_048_576
    if "claude" in m or p == "anthropic":
        return 200_000
    if "gpt-4" in m or "o1" in m or "o3" in m or "o4" in m or p == "openai":
        return 128_000
    return 131_072


def resolve_context_length_for_session_model(
    model: str | None,
    provider: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> int:
    """Resolve current context capacity without depending on an HTTP router.

    Four sources, most trustworthy first:

      1. An explicit ``context_length`` in config for this model.
      2. The provider itself, asked over its API (see
         :func:`_probe_provider_context_length`). For Ollama Cloud this
         is ``/api/show`` — the number the chat-tab ring must display.
      3. ``agent.model_metadata`` — optional bundled table. A family
         catch-all here (anything named "qwen" → 131072) must not beat
         a live probe (qwen3.5:397b is 262144).
      4. :func:`_estimate_model_context_length` — a keyword guess.

    The agent import used to be the first statement of one big ``try``
    wrapping all of this, so on an install without that optional package
    the ``ModuleNotFoundError`` skipped straight to the keyword guess and
    the operator's own configured value was never read. Each source now
    fails independently.
    """
    model_for_lookup = str(model or "").strip()
    if not model_for_lookup:
        return 0

    try:
        from api.config import get_config

        cfg = get_config()
    except Exception:
        cfg = {}
    try:
        lookup = context_length_lookup_inputs_for_model(
            model_for_lookup,
            provider,
            base_url=base_url,
            api_key=api_key,
            cfg=cfg if isinstance(cfg, dict) else {},
        )
    except Exception:
        lookup = ContextLengthLookupInputs()

    serving_provider = lookup.provider or provider
    ollama_lane = bool(
        _ollama_probe_provider(serving_provider)
        or str(serving_provider or "").strip().lower() in _JAEGER_WORKER_IDS
    )

    # Ollama / Jaeger: a live ``/api/show`` window beats the bundled
    # family table (qwen → 131072). An explicit config value still wins.
    if ollama_lane:
        if lookup.config_context_length:
            return lookup.config_context_length
        probed = _probe_provider_context_length(
            model_for_lookup,
            serving_provider,
            api_key=lookup.api_key or api_key,
        )
        if probed > 0:
            return probed

    # Other providers: keep the established metadata → config → probe
    # order so global caps still flow through get_model_context_length.
    try:
        from agent.model_metadata import get_model_context_length
    except Exception:
        get_model_context_length = None
    if get_model_context_length is not None:
        try:
            res = get_model_context_length(
                model_for_lookup,
                lookup.base_url,
                api_key=lookup.api_key,
                config_context_length=lookup.config_context_length,
                # Spelled out rather than via ``serving_provider`` so the
                # #1896 guard can still see the override args at this
                # callsite; the two are the same value.
                provider=lookup.provider or provider or "",
                custom_providers=lookup.custom_providers,
            ) or 0
            if res > 0:
                return res
        except TypeError:
            try:
                res = get_model_context_length(model_for_lookup, lookup.base_url) or 0
                if res > 0:
                    return res
            except Exception:
                pass
        except Exception:
            pass

    if lookup.config_context_length:
        return lookup.config_context_length

    if not ollama_lane:
        probed = _probe_provider_context_length(
            model_for_lookup,
            serving_provider,
            api_key=lookup.api_key or api_key,
        )
        if probed > 0:
            return probed

    return _estimate_model_context_length(model_for_lookup, provider)


# Compatibility names preserve the established regression-test vocabulary while
# ownership moves out of the legacy route dispatcher.
_context_length_lookup_inputs_for_model = context_length_lookup_inputs_for_model
_resolve_context_length_for_session_model = resolve_context_length_for_session_model
_should_accept_session_context_length_refresh = should_accept_context_length_refresh


def model_matches_configured_default(
    session_model: str | None,
    configured_default: str | None,
    provider: str | None = None,
) -> bool:
    """Compare default-model identities across bare and qualified forms."""
    return _matches_default(
        str(session_model or "").strip(),
        str(configured_default or "").strip(),
        str(provider or "").strip(),
    )


def session_context_length_lookup_state(
    model: str | None,
    provider: str | None,
) -> tuple[str, str, str, str]:
    """Resolve transport-neutral inputs for session context metadata lookup."""
    model_value = str(model or "").strip()
    provider_value = str(provider or "").strip()
    if not model_value:
        return "", provider_value, "", ""
    base_url = ""
    api_key = ""
    try:
        from api.config import model_with_provider_context, resolve_model_provider

        qualified = model_with_provider_context(model_value, provider_value or None)
        resolved_model, resolved_provider, resolved_base = resolve_model_provider(qualified)
        model_value = str(resolved_model or model_value).strip()
        provider_value = str(resolved_provider or provider_value).strip()
        base_url = str(resolved_base or "").strip()
    except Exception:
        logger.debug("Session context lookup resolution failed", exc_info=True)
    if provider_value.startswith("custom:"):
        try:
            from api.config import resolve_custom_provider_connection

            custom_key, custom_base = resolve_custom_provider_connection(provider_value)
            api_key = str(custom_key or "").strip()
            base_url = base_url or str(custom_base or "").strip()
        except Exception:
            logger.debug("Custom context lookup resolution failed", exc_info=True)
    return model_value, provider_value, base_url, api_key


def session_model_identity_matches(
    stored_model: str | None,
    stored_provider: str | None,
    resolved_model: str | None,
    resolved_provider: str | None,
) -> bool:
    """Compare model identities without conflating distinct providers."""
    stored = str(stored_model or "").strip()
    resolved = str(resolved_model or "").strip()
    if not stored or not resolved:
        return False

    def split(value: str) -> tuple[str, str | None]:
        bare, explicit = _split_qualified_model(value)
        if explicit is None and "/" in value:
            prefix, suffix = value.split("/", 1)
            if prefix.strip() and suffix.strip():
                return suffix.strip(), prefix.strip()
        return bare, explicit

    stored_bare, stored_explicit = split(stored)
    resolved_bare, resolved_explicit = split(resolved)
    stored_lane = _canonical_provider(stored_explicit or stored_provider)
    resolved_lane = _canonical_provider(resolved_explicit or resolved_provider)
    if stored == resolved and stored_lane == resolved_lane:
        return True
    if stored_bare != resolved_bare:
        return False
    return not (stored_lane and resolved_lane) or stored_lane == resolved_lane


def session_context_projection(
    session,
    effective_model: str | None,
    effective_provider: str | None,
    *,
    resolve_model: bool = True,
) -> tuple[int, int]:
    """Return the context window and proportionally adjusted threshold for a session response."""
    persisted = int(getattr(session, "context_length", 0) or 0)
    threshold = int(getattr(session, "threshold_tokens", 0) or 0)
    if persisted and not resolve_model:
        return persisted, threshold
    stored_model = str(getattr(session, "model", "") or "").strip()
    stored_provider = str(getattr(session, "model_provider", "") or "").strip()
    model, provider, base_url, api_key = session_context_length_lookup_state(
        effective_model or stored_model,
        effective_provider or stored_provider,
    )
    resolved = resolve_context_length_for_session_model(
        model,
        provider,
        base_url=base_url,
        api_key=api_key,
    )
    changed = not session_model_identity_matches(
        stored_model,
        stored_provider,
        model,
        provider,
    )
    if not should_accept_context_length_refresh(persisted, resolved, model_changed=changed):
        return persisted, threshold
    if persisted and resolved != persisted and threshold > 0:
        threshold = max(1, int(threshold * resolved / persisted))
    if resolved and resolved != persisted:
        try:
            session.context_length = resolved
            session.threshold_tokens = threshold
            save = getattr(session, "save", None)
            if callable(save):
                save()
        except Exception:
            logger.debug("Could not persist resolved context_length", exc_info=True)
    return resolved, threshold


_model_matches_configured_default = model_matches_configured_default
_session_context_length_lookup_state = session_context_length_lookup_state
_session_model_identity_matches = session_model_identity_matches


__all__ = [
    "ContextLengthLookupInputs",
    "_context_length_lookup_inputs_for_model",
    "_should_accept_session_context_length_refresh",
    "context_length_lookup_inputs_for_model",
    "normalize_provider_id",
    "model_matches_configured_default",
    "resolve_context_length_for_session_model",
    "session_context_length_lookup_state",
    "session_context_projection",
    "session_model_identity_matches",
    "should_accept_context_length_refresh",
]
