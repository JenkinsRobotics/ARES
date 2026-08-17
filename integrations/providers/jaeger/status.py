"""JaegerAI readiness across all three of its execution paths.

JaegerAI is the hardest case in the provider layout, and the reason the status
contract is deliberately transport-agnostic: it can serve a turn through an HTTP
gateway, through a local ``jaeger bridge`` subprocess speaking NDJSON over
stdio, or not at all. ``gateway_streaming`` picks between the first two at turn
time, preferring the **local bridge** whenever no gateway URL is configured.

The previous check (``api.backend_selector.is_jros_available``) only probed the
gateway, and its docstring stated the intent plainly: "A local checkout alone is
install-detected, not available." That was wrong in practice — the bridge is the
default execution path, not a fallback — so a perfectly working bridge-only
install reported "JaegerAI is not installed or reachable." and was filtered out
of the model picker entirely.

This module reports on whichever transport would actually run the next turn.
"""
from __future__ import annotations

import logging
import os
import time

from api.providers.status_contract import (
    ProviderStatus,
    connected,
    not_installed,
    offline,
)

logger = logging.getLogger(__name__)

# Health is polled on hot paths (every connection listing, every chat start), so
# results are cached briefly. Mirrors the TTL the old backend_selector used.
_CACHE_TTL = 5.0
_cached: ProviderStatus | None = None
_cached_at = 0.0


def _bridge_launcher_ready(root) -> bool:
    """Whether ``root`` holds a ``jaeger`` launcher this process could execute.

    Checked inside the *discovered* root rather than at the env-derived home,
    because that root is exactly what ``_get_or_start_bridge_client`` passes to
    ``JrosClient`` as its jaeger home — checking anywhere else would answer a
    question about a different install.

    Deliberately a filesystem check rather than a subprocess spawn: this runs on
    every health poll, and starting JaegerAI to ask whether it can start would
    be both slow and side-effecting.
    """
    try:
        launcher = root / "jaeger"
        return launcher.is_file() and os.access(launcher, os.X_OK)
    except Exception:
        logger.debug("JaegerAI launcher probe failed", exc_info=True)
        return False


def _uncached_status() -> ProviderStatus:
    from api.providers.jaeger.gateway_streaming import (
        jros_gateway_base_url,
        jros_gateway_health,
        local_jros_root,
    )

    gateway_url = ""
    try:
        gateway_url = jros_gateway_base_url()
    except Exception:
        logger.debug("JaegerAI gateway URL resolution failed", exc_info=True)

    # 1. A configured gateway is an explicit operator choice, so it is checked
    #    first and its failure is reported rather than silently masked by the
    #    bridge.
    if gateway_url:
        try:
            reply = jros_gateway_health(timeout=1.0)
        except Exception:
            logger.debug("JaegerAI gateway health probe failed", exc_info=True)
            reply = None
        if reply is not None:
            return connected(
                "JaegerAI gateway is responding.",
                mode="gateway",
                gateway_url=gateway_url,
                model=reply.get("model"),
                provider=reply.get("provider"),
                instance=reply.get("instance"),
                booted=bool(reply.get("booted")),
            )
        return offline(
            f"JaegerAI gateway is configured at {gateway_url} but is not responding. "
            "Current JaegerAI ships no gateway server, so this endpoint is "
            "most likely stale — clear it to use the local bridge instead. "
            "(See ADR-0008: the HTTP gateway path is vestigial.)",
            mode="gateway",
            gateway_url=gateway_url,
            reason=f"Nothing answered a health probe at {gateway_url}.",
            fix=(
                "Unset ARES_JAEGER_GATEWAY_URL to fall back to the local bridge, "
                "or start the server listening at that address."
            ),
        )

    # 2. No gateway configured: the local bridge is what actually runs turns.
    try:
        root = local_jros_root()
    except Exception:
        logger.debug("JaegerAI local root discovery failed", exc_info=True)
        root = None

    if root is None:
        # Root resolution is fail-closed on an explicit override, so a stale
        # variable left over from an older install (a renamed or deleted
        # checkout) looks exactly like "nothing installed" — and the generic
        # message tells the user to set the very variable that is already set
        # and is the cause. Name the variable and its value instead; a
        # misconfiguration the user cannot see is one they cannot fix.
        from api.providers.jaeger.paths import configured_root_override

        try:
            override = configured_root_override()
        except Exception:
            logger.debug("JaegerAI override lookup failed", exc_info=True)
            override = None

        if override is not None:
            name, value = override
            return not_installed(
                f"{name} points at {value}, which is not a JaegerAI install. "
                "Update it to your JaegerAI checkout, or unset it to let ARES "
                "discover one automatically.",
                mode="bridge",
                configured_by=name,
                configured_root=value,
                reason=f"{name} is set to {value}, which is not a JaegerAI install.",
                fix=f"Point {name} at your JaegerAI checkout, or unset it: unset {name}",
                env_hint="With no override set, ARES uses its shared Jaeger path resolver.",
            )

        return not_installed(
            "JaegerAI is not installed. Install it, or set ARES_JAEGER_HOME / "
            "ARES_JAEGER_GATEWAY_URL to point at an existing instance.",
            reason="The shared Jaeger path resolver found no runnable install.",
            fix="Install JaegerAI, or set ARES_JAEGER_HOME=/path/to/JaegerAI",
            env_hint="A checkout counts only if it has a jaeger_ai/ directory and an executable jaeger launcher.",
        )

    if not _bridge_launcher_ready(root):
        # A source checkout or partial install is detected but cannot execute a
        # turn: the bridge has no launcher to spawn. Reported as not installed
        # rather than needs_attention, because nothing here is runnable —
        # "detected on disk" is not the same as "can serve a request".
        return not_installed(
            f"JaegerAI was found at {root} but has no runnable `jaeger` launcher. "
            "Complete the install so the launcher is present and executable.",
            mode="bridge",
            root=str(root),
            reason=f"{root}/jaeger is missing or not executable.",
            fix=f"Finish the JaegerAI install, then: chmod +x {root}/jaeger",
        )

    # The bridge protocol carries no model field, so unlike the gateway branch
    # there is no reply to read a model out of. The instance config is the
    # authoritative selection instead — it is the file ARES's own write path
    # (ares_provider_sync.sync_provider) edits, and the one JaegerAI boots
    # from. Reporting it here is what lets `active_model` be non-null on the
    # transport that actually runs turns.
    from api.providers.jaeger.active_model import active_model
    from api.providers.jaeger.paths import jros_instance_name

    selection = active_model()
    model = selection.get("model")
    return connected(
        (
            f"JaegerAI is available through the local bridge, running {model}."
            if model
            else "JaegerAI is available through the local bridge."
        ),
        mode="bridge",
        root=str(root),
        instance=jros_instance_name(),
        model=model,
        provider=selection.get("provider"),
        model_location=selection.get("location"),
        model_source=selection.get("source"),
        config_path=selection.get("config_path"),
    )


def check_status(*, use_cache: bool = True) -> ProviderStatus:
    """Current JaegerAI readiness, cached for a few seconds."""
    global _cached, _cached_at

    now = time.monotonic()
    if use_cache and _cached is not None and (now - _cached_at) < _CACHE_TTL:
        return _cached

    try:
        status = _uncached_status()
    except Exception as exc:
        logger.debug("JaegerAI status probe failed", exc_info=True)
        status = offline(f"JaegerAI status could not be determined: {exc}")

    _cached = status
    _cached_at = now
    return status


def reset_cache() -> None:
    """Drop the cached status (used by tests and after config changes)."""
    global _cached, _cached_at

    _cached = None
    _cached_at = 0.0
