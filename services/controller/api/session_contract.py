"""ARES projection of the versioned Jaeger session ownership contract."""

from __future__ import annotations

import logging
from typing import Any

from api.backend_catalog import JAEGER_BACKEND_ID
from api.backend_selector import get_active_backend, get_session_backend
from api.contracts import (
    MIN_SUPPORTED_SESSION_CONTRACT_VERSION,
    SESSION_CONTRACT_VERSION,
)


logger = logging.getLogger(__name__)


class SessionCapabilityError(RuntimeError):
    """The selected runtime cannot safely perform a session operation."""


def shared_session_id(value: object) -> str:
    """Return the opaque cross-runtime identifier without namespacing it."""
    session_id = str(value or "").strip()
    if not session_id or len(session_id) > 256:
        raise ValueError("invalid session id")
    return session_id


def backend_for_session(session: Any | None = None) -> str:
    from api.config import get_config

    config = get_config()
    if isinstance(session, dict):
        from api.backend_selector import normalize_backend

        explicit = normalize_backend(session.get("ares_backend"))
        return explicit or get_active_backend(config)
    return get_session_backend(session, config) if session is not None else get_active_backend(config)


def contract_for_backend(backend: str) -> dict[str, Any] | None:
    if backend != JAEGER_BACKEND_ID:
        return None
    from api.ares_capabilities import capability_contract_for_backend

    integration = capability_contract_for_backend(backend).get("runtime_contract")
    if not isinstance(integration, dict):
        return None
    feature = (integration.get("features") or {}).get("sessions")
    contract = feature.get("contract") if isinstance(feature, dict) else None
    return contract if isinstance(contract, dict) else None


def require_operation(operation: str, *, session: Any | None = None, backend: str = "") -> dict[str, Any] | None:
    """Fail closed when Jaeger is selected but lacks the requested v2 operation.

    Legacy runtimes retain ARES-owned persistence. Only a runtime that declares
    Jaeger transcript ownership is routed through the canonical bridge.
    """
    from api.providers.jaeger.paths import jaeger_integration_disabled

    if jaeger_integration_disabled():
        return None
    if session is not None and not backend:
        owner = (
            session.get("transcript_owner")
            if isinstance(session, dict)
            else getattr(session, "transcript_owner", None)
        )
        if owner != "jaeger":
            return None
    selected = backend or backend_for_session(session)
    if selected != JAEGER_BACKEND_ID:
        return None
    contract = contract_for_backend(selected)
    if not contract or int(contract.get("version") or 0) < 2:
        raise SessionCapabilityError(
            "Jaeger does not expose the required v2 session contract"
        )
    capability = (contract.get("operations") or {}).get(operation)
    if not isinstance(capability, dict) or capability.get("available") is not True:
        raise SessionCapabilityError(
            f"Jaeger does not support the session {operation} operation"
        )
    return capability


def is_operation_available(operation: str, *, session: Any | None = None, backend: str = "") -> bool:
    """Non-raising predicate form of require_operation().

    Callers that want to *probe* the Jaeger session contract — rather than
    fail a request on it — ask here. Any negotiation failure answers False so
    the caller falls back to ARES-owned handling rather than surfacing a 500
    (DOCTRINE #4: capability-negotiated contracts fail closed).
    """
    try:
        return require_operation(operation, session=session, backend=backend) is not None
    except SessionCapabilityError:
        return False
    except Exception:  # bridge unreachable, malformed contract, negotiation error
        logger.debug("session contract probe failed for %r", operation, exc_info=True)
        return False


def runtime_owns_transcript(session: Any | None = None, *, backend: str = "") -> bool:
    if session is not None:
        owner = (
            session.get("transcript_owner")
            if isinstance(session, dict)
            else getattr(session, "transcript_owner", None)
        )
        return owner == "jaeger"
    selected = backend or backend_for_session(session)
    contract = contract_for_backend(selected)
    return bool(contract and (contract.get("ownership") or {}).get("transcript") == "jaeger")


def runtime_command(operation: str, session_id: str, **args: Any) -> dict[str, Any]:
    from api.providers.jaeger.streaming import command_local_companion

    command = {
        "create": "create_session",
        "clear": "clear_session",
        "delete": "delete_session",
    }.get(operation)
    if not command:
        raise ValueError(f"session operation {operation!r} is not Jaeger-owned")
    payload = {"id": shared_session_id(session_id), **args}
    result = command_local_companion(command, payload)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise SessionCapabilityError(f"Jaeger session {operation} failed")
    return result


def runtime_query(operation: str, *, session_id: str = "", query: str = "", limit: int = 500):
    from api.providers.jaeger.streaming import query_local_companion

    if operation == "list":
        return query_local_companion("list_sessions", {"limit": limit})
    if operation == "load":
        return query_local_companion(
            "load_session", {"id": shared_session_id(session_id), "resume": False}
        )
    if operation == "search":
        return query_local_companion("search_sessions", {"query": query, "limit": limit})
    raise ValueError(f"unsupported session query {operation!r}")
