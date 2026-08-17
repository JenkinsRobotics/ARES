"""Which model a JaegerAI instance will actually run the next turn on.

ARES selects JaegerAI models through the bridge's validated ``configure_model``
command and reads the serving model back through ``serving_model``. ARES does
not edit or traverse Jaeger's runtime configuration for normal operation.

The consequence was visible in ``/api/jaeger-onboarding/status``: the bridge
branch of :mod:`api.providers.jaeger.status` reported ``mode`` and ``root`` but
no model, so ``active_model`` was always ``null`` and ``models_are_live``
always ``false`` — ARES could change JaegerAI's model but could not say which
one was in force. The instance listing was worse than silent: it read only
``model.model_path`` and so reported the *local* model even while
``external_model.enabled`` meant a cloud model was actually serving turns.

The bridge's ``serving_model`` query is authoritative because it distinguishes
configured intent from the lane that actually booted. The pure
``describe_config`` helper remains for read-only instance discovery and tests;
it is not the normal runtime state path.

Deliberately config-derived and never a recommendation fallback: callers use
this to label a live runtime, and a guess presented as the active model is the
failure mode ``models_are_live`` exists to prevent. When nothing can be read,
every field is ``None`` and callers report "unknown" rather than a default.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: JROS provider slugs that phone out to a hosted API. Used only to label a
#: selection for the UI; the runnable-provider list lives in
#: ``api.ares_provider_sync.PROVIDER_PRESETS``.
CLOUD_PROVIDERS = frozenset(
    {"anthropic", "gemini", "ollama-cloud", "openai", "xai"}
)


def _load_config(path: Path) -> dict[str, Any]:
    try:
        import yaml

        if not path.is_file():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.debug("Failed to read JaegerAI config at %s", path, exc_info=True)
        return {}


def describe_config(config: dict[str, Any]) -> dict[str, Any]:
    """Resolve one already-loaded instance config to its effective model.

    Split from :func:`active_model` so the instance listing can describe each
    discovered instance from the config it has already read, without a second
    resolution pass that could disagree with this one.
    """
    unknown: dict[str, Any] = {
        "model": None,
        "provider": None,
        "location": None,
        "base_url": None,
        "source": None,
        "ctx": None,
    }
    if not isinstance(config, dict):
        return unknown

    external = config.get("external_model")
    if isinstance(external, dict) and external.get("enabled"):
        model = str(external.get("model") or "").strip()
        provider = str(external.get("provider") or "").strip().lower()
        if model:
            return {
                "model": model,
                "provider": provider or None,
                "location": "cloud" if provider in CLOUD_PROVIDERS else "local",
                "base_url": str(external.get("base_url") or "").strip() or None,
                "source": "external_model",
                "ctx": _positive_ctx(external.get("ctx")),
            }
        # enabled with no model is a broken selection, not a local one: fall
        # through to report unknown rather than silently naming the on-device
        # model JaegerAI is not going to use.
        return unknown

    model_block = config.get("model")
    if isinstance(model_block, dict):
        model_path = str(model_block.get("model_path") or "").strip()
        if model_path:
            return {
                # The bare directory/file name is what the model catalog lists
                # local models under, so selection round-trips: what status
                # reports can be handed straight back to /api/model/set.
                "model": Path(model_path).name,
                "provider": "local",
                "location": "local",
                "base_url": None,
                "source": "model.model_path",
                "model_path": model_path,
                "ctx": _positive_ctx(model_block.get("ctx")),
            }
    return unknown


def _positive_ctx(value: Any) -> int | None:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def active_model(config_path: Path | None = None) -> dict[str, Any]:
    """Return the effective model for the instance ARES would run a turn on.

    An explicit ``config_path`` is retained only for isolated read-only callers
    and tests. Normal operation asks the running Jaeger bridge.
    """
    if config_path is None:
        try:
            from api.providers.jaeger.gateway_streaming import query_local_companion

            payload = query_local_companion("serving_model", {})
            if isinstance(payload, dict):
                row = payload.get("serving") or payload.get("configured")
                if isinstance(row, dict):
                    return {
                        "model": row.get("model"),
                        "provider": row.get("provider"),
                        "location": "local" if row.get("provider") in {"local", "in-process"} else "cloud",
                        "base_url": row.get("base_url"),
                        "source": "jaeger_bridge",
                        "ctx": row.get("context_length"),
                        "config_path": None,
                    }
        except Exception:
            logger.debug("JaegerAI serving-model query failed", exc_info=True)
        return {
            "model": None, "provider": None, "location": None,
            "base_url": None, "source": None, "ctx": None, "config_path": None,
        }

    described = describe_config(_load_config(config_path))
    described["config_path"] = str(config_path)
    return described


__all__ = ["CLOUD_PROVIDERS", "active_model", "describe_config"]
