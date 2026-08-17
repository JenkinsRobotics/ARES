"""Readiness for JaegerAI's supported stdio bridge transport."""
from __future__ import annotations

import logging
import os
import time

from api.providers.status_contract import ProviderStatus, connected, not_installed, offline

logger = logging.getLogger(__name__)
_CACHE_TTL = 5.0
_cached: ProviderStatus | None = None
_cached_at = 0.0


def _uncached_status() -> ProviderStatus:
    from api.providers.jaeger.paths import configured_root_override, jaeger_instance_name
    from api.providers.jaeger.streaming import local_jaeger_root

    root = local_jaeger_root()
    if root is None:
        override = configured_root_override()
        if override:
            name, value = override
            return not_installed(
                f"{name} points at {value}, which is not a JaegerAI install.",
                mode="bridge", configured_by=name, configured_root=value,
                reason=f"{name} is invalid.", fix=f"Correct or unset {name}.",
            )
        return not_installed(
            "JaegerAI is not installed.", mode="bridge",
            reason="No runnable JaegerAI product root was found.",
            fix="Install JaegerAI or set ARES_JAEGER_HOME=/path/to/JaegerAI.",
        )
    launcher = root / "jaeger"
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        return not_installed(
            f"JaegerAI at {root} has no executable launcher.", mode="bridge",
            reason=f"{launcher} is missing or not executable.",
            fix=f"Complete the JaegerAI install and make {launcher} executable.",
        )
    try:
        from api.providers.jaeger.active_model import active_model

        selection = active_model()
    except Exception:
        selection = {}
    model = selection.get("model")
    return connected(
        f"JaegerAI is available through the local bridge{f', running {model}' if model else ''}.",
        mode="bridge", root=str(root), instance=jaeger_instance_name(), model=model,
        provider=selection.get("provider"), model_location=selection.get("location"),
        model_source=selection.get("source"),
    )


def check_status(*, use_cache: bool = True) -> ProviderStatus:
    global _cached, _cached_at
    now = time.monotonic()
    if use_cache and _cached is not None and now - _cached_at < _CACHE_TTL:
        return _cached
    try:
        result = _uncached_status()
    except Exception as exc:
        logger.debug("JaegerAI status probe failed", exc_info=True)
        result = offline(f"JaegerAI status could not be determined: {exc}")
    _cached, _cached_at = result, now
    return result


def status() -> dict[str, object]:
    """Dictionary form retained for the generic worker registry."""
    return check_status().as_dict()


def reset_cache() -> None:
    global _cached, _cached_at
    _cached, _cached_at = None, 0.0
