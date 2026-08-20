"""
ARES Identity Layer — centralized source of truth for assistant display name,
backend badge rendering, and identity metadata.

This module provides a single authoritative source for:
  - assistantDisplayName: what the assistant calls itself in the UI
  - backend badge: the visual label shown next to assistant messages
  - identity metadata: structured info for the frontend identity API

Both Python (server-side rendering) and JavaScript (client-side) consume
this module. The frontend polls /api/ares/identity to stay in sync.
"""

from __future__ import annotations

import logging
import datetime
import json
from typing import Any, Dict

from api.paths import HOME

logger = logging.getLogger(__name__)


_DEFAULT_AI_FALLBACK = "ARES Assistant"


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _profile_display_name(profile: str | None) -> str | None:
    value = _clean_text(profile)
    if value and value != "default":
        return value[0].upper() + value[1:]
    return None


def _is_placeholder_assistant_name(value: str | None) -> bool:
    return _clean_text(value).lower() in {"", "ares", "ares agent", "jaeger"}


def _persona_display_name(persona_id: str | None) -> str | None:
    pid = _clean_text(persona_id)
    if not pid:
        return None
    try:
        from api.persona import load_persona

        persona = load_persona(pid)
    except Exception:
        logger.debug("Failed to load persona %s for identity display", pid, exc_info=True)
        persona = None
    if isinstance(persona, dict):
        identity = persona.get("identity") if isinstance(persona.get("identity"), dict) else {}
        name = _clean_text(identity.get("display_name")) or _clean_text(persona.get("name"))
        if name:
            return name
    return pid.replace("_", " ").replace("-", " ").title()


def _jaeger_live_display_name() -> str | None:
    """Who Jaeger says is answering — the selected character, not identity.yaml.

    ``bot_name`` / identity.yaml is the instance's own name (often still
    "Jarvis" after a character swap). Prefer the live character sheet:
    its id first (so a stale display_name cannot pin the chat header),
    then display_name, then the character label.
    """
    try:
        from api.providers.jaeger.streaming import query_local_companion

        identity = query_local_companion("identity", {})
        if not isinstance(identity, dict):
            return None
        cid = _clean_text(identity.get("character_id"))
        if cid and cid.lower() not in {"assistant", "default"}:
            persona = _persona_display_name(cid)
            if persona:
                return persona
            character = _clean_text(identity.get("character"))
            if character:
                return character
        name = _clean_text(identity.get("display_name"))
        if name:
            return name
        character = _clean_text(identity.get("character"))
        if character and character.lower() != "assistant":
            return character
        return _clean_text(identity.get("agent_name")) or None
    except Exception:
        logger.debug("Failed to query Jaeger identity", exc_info=True)
        return None


def _jaeger_default_agent_name() -> str | None:
    return _jaeger_live_display_name()


def _default_assistant_name(bot_name: str | None) -> str:
    saved = _clean_text(bot_name)
    if saved and not _is_placeholder_assistant_name(saved):
        return saved
    return _jaeger_default_agent_name() or _DEFAULT_AI_FALLBACK


def _normalize_backend(value: str | None) -> str:
    from api.backend_selector import normalize_backend

    return normalize_backend(value)


def log_audit_event(session_id: str, action: str, details: str, status: str) -> None:
    """Log a safety/security event to the centralized ARES audit log.

    Saves a JSON line to ~/.ares/audit.log.
    """
    audit_dir = HOME / ".ares"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_file = audit_dir / "audit.log"
    
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "session_id": session_id,
        "action": action,
        "details": details,
        "status": status,
    }
    
    try:
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning("Failed to write to audit log: %s", exc)


def get_assistant_display_name(
    *,
    profile: str | None = None,
    bot_name: str | None = None,
    backend: str = "",
    persona_id: str | None = None,
) -> str:
    """Return the canonical assistant display name.

    Resolution order:
      1. If a non-default WebUI profile is active, keep that profile label.
      2. If JaegerAI is active and a character is selected, show the
         character/person being messaged.
      3. Otherwise show the user's default AI name from settings/JaegerAI identity.
      4. Fall back to a neutral product label for incomplete setup.
    """
    profile_name = _profile_display_name(profile)
    if profile_name:
        return profile_name

    # Live Jaeger character wins even when the backend slug is missing or
    # still the instance name — that's how the header stayed stuck on
    # "Jarvis" after picking Anakin.
    live = _jaeger_live_display_name()
    if live:
        return live

    normalized_backend = _normalize_backend(backend)
    if normalized_backend == "jaeger_local":
        persona_name = _persona_display_name(persona_id)
        if persona_name:
            return persona_name

    return _default_assistant_name(bot_name)


def get_backend_badge_html(backend: str) -> str:
    """Return the HTML for a backend badge."""
    normalized_backend = _normalize_backend(backend)
    label = get_backend_display_name(normalized_backend)
    return f' <span class="msg-backend-badge" title="{label} runtime">{label}</span>'


def get_backend_display_name(backend: str) -> str:
    """Return the human-readable display name for a backend key."""
    normalized_backend = _normalize_backend(backend)
    if not normalized_backend:
        return "No runtime selected"
    from api.backend_selector import backend_label

    return backend_label(normalized_backend)


def build_identity_payload(
    *,
    profile: str | None = None,
    bot_name: str | None = None,
    backend: str = "",
    persona_id: str | None = None,
) -> Dict[str, Any]:
    """Build the full identity payload for the /api/ares/identity endpoint.

    Returns a dict with:
      - display_name: str — what the assistant calls itself
      - backend: str — the active backend key
      - backend_label: str — human-readable backend name
      - backend_badge_html: str — HTML for the backend badge (or empty)
    """
    normalized_backend = _normalize_backend(backend)
    display_name = get_assistant_display_name(
        profile=profile, bot_name=bot_name, backend=normalized_backend, persona_id=persona_id
    )
    character_name = (
        _persona_display_name(persona_id)
        if normalized_backend == "jaeger_local" and _clean_text(persona_id)
        else None
    )
    return {
        "display_name": display_name,
        "backend": normalized_backend,
        "backend_label": get_backend_display_name(normalized_backend),
        "backend_badge_html": get_backend_badge_html(normalized_backend),
        "identity_kind": "character" if character_name else "default",
        "selected_character": _clean_text(persona_id) if character_name else "",
        "selected_character_name": character_name or "",
        "default_display_name": _default_assistant_name(bot_name),
    }
