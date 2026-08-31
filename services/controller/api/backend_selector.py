"""ARES Backend Selector — routes agent execution to any registered backend.

Paperclip pattern: flat registry, agnostic naming. Each backend is
{name}_{deployment}. No roles, no opinions. The UI iterates the map.
"""
from __future__ import annotations

import logging

from .backend_catalog import (
    JAEGER_BACKEND_ID,
    VALID_BACKEND_IDS,
    backend_display_name,
    normalize_backend_id,
)
from .backends.router import get_router

logger = logging.getLogger(__name__)

BACKEND_JAEGER = JAEGER_BACKEND_ID
VALID_BACKENDS = VALID_BACKEND_IDS

def normalize_backend(value: object, *, fallback: str = "") -> str:
    return normalize_backend_id(value, fallback=fallback)


def get_active_backend(config: dict) -> str:
    """Return the elected external runtime, or an empty string.

    An explicit election always wins — this never second-guesses a runtime the
    user picked. Only when nothing has been elected does JaegerAI become the
    default, and only when it can actually serve a turn right now: it is the
    assistant ARES is built around, so on a machine where it is ready it should
    not lose the default to whichever other worker happens to be installed.
    When it is not ready the result stays empty, which is what surfaces the
    "choose a provider" state rather than electing a silent substitute.
    """
    elected = normalize_backend((config or {}).get("ares_backend", ""))
    if elected:
        return elected

    try:
        if is_jaeger_available():
            return BACKEND_JAEGER
    except Exception:
        logger.debug("JaegerAI availability probe failed during election", exc_info=True)
    return ""


def get_session_backend(session: object, config: dict) -> str:
    # A persisted election is authoritative and must remain a pure metadata
    # lookup.  Probing the live default first made every session projection
    # wait on Jaeger even when the row already named another backend.
    explicit = normalize_backend(getattr(session, "ares_backend", None))
    return explicit or get_active_backend(config)


def is_jaeger_available() -> bool:
    """Whether JaegerAI can run a turn through its supported bridge."""

    from api.providers.jaeger.status import check_status

    return check_status().available


def jaeger_connection_details() -> dict:
    """Non-secret details from the last JaegerAI status probe.

    Includes the negotiated transport mode and owner-provided runtime details.
    """

    from api.providers.jaeger.status import check_status

    return dict(check_status().details or {})


def backend_status() -> dict:
    """Return current backend availability for UI display.

    Note: this probes *every* registered backend and is intentionally not used
    on the chat start hot path (use :func:`is_jaeger_available` /
    per-backend ``is_available`` instead).
    """
    router = get_router()
    status = {
        name: backend.is_available()
        for name, backend in router.list_all().items()
        if normalize_backend(name) != JAEGER_BACKEND_ID
    }
    jaeger_available = is_jaeger_available()
    status[JAEGER_BACKEND_ID] = jaeger_available
    if jaeger_available:
        for key, value in jaeger_connection_details().items():
            status[f"jaeger_{key}"] = value
    return status


def backend_label(backend: str) -> str:
    """Human-readable label for the backend selector dropdown."""
    return backend_display_name(backend) or backend
