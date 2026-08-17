"""ARES onboarding adapter for Jaeger-owned Companion operations.

Defaults, existence checks, and instance creation use the versioned Jaeger
bridge. Installation remains an explicit operator action outside ARES.
"""
from __future__ import annotations

import logging
from typing import Any

from api.providers.jaeger.streaming import local_jaeger_root

logger = logging.getLogger(__name__)

def companion_available() -> bool:
    """True when a local JaegerAI install is present for the naming step."""
    try:
        return local_jaeger_root() is not None
    except Exception:
        logger.debug("Companion availability probe failed", exc_info=True)
        return False


def companion_exists() -> bool:
    """True when a Companion instance has already been created."""
    try:
        from api.providers.jaeger.streaming import query_local_companion

        result = query_local_companion("instance_exists", {})
        return bool(result.get("exists"))
    except Exception:
        logger.debug("Companion existence check failed", exc_info=True)
        return False


def companion_setup_defaults() -> dict[str, Any]:
    """Host-tier model recommendation, voices, permission modes, and the
    character roster — the same recommendations ``jaeger agent create``'s
    terminal wizard prints, served for ARES's web onboarding instead."""
    from api.providers.jaeger.streaming import query_local_companion

    result = query_local_companion("setup_defaults", {})
    if not isinstance(result, dict):
        raise RuntimeError("Jaeger returned invalid setup defaults")
    return result


def list_characters() -> list[dict[str, str]]:
    """Characters available to play the Companion (id, name, role, voice)."""
    return companion_setup_defaults().get("characters", [])


def create_companion(
    *,
    character_id: str | None = None,
    name: str | None = None,
    display_name: str | None = None,
    role: str | None = None,
    personality: str | None = None,
    voice_id: str | None = None,
    awake_model: str | None = None,
    asleep_model: str | None = None,
    permission_mode: str = "confirm",
    make_default: bool = True,
) -> dict[str, Any]:
    """Ask Jaeger's bridge to create the Companion with its validated service."""
    resolved_character_id = (character_id or "").strip()
    if not resolved_character_id or resolved_character_id == "default":
        # Fall back to the first available character when the user picks
        # "Default (no character)" — the user's name, display_name and
        # personality override the character's identity anyway.
        roster = list_characters()
        if not roster:
            raise ValueError("No characters are installed. Install JaegerAI characters first.")
        resolved_character_id = roster[0]["id"]

    from api.providers.jaeger.streaming import command_local_companion

    result = command_local_companion(
        "create_instance",
        {
            "character_id": resolved_character_id,
            "name": name,
            "display_name": display_name,
            "role": role,
            "personality": personality,
            "voice_id": voice_id,
            "awake_model": awake_model,
            "asleep_model": asleep_model,
            "permission_mode": permission_mode,
            "interaction_mode": "gui",
            "make_default": make_default,
        },
    )
    if not isinstance(result, dict):
        raise RuntimeError("Jaeger returned an invalid instance-creation result")
    result = {
        "ok": True,
        "name": result.get("instance"),
        "instance_dir": result.get("root"),
        "owner": "jaeger",
    }
    return result
