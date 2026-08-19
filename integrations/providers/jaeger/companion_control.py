"""Normalized ARES control surface for the selected JaegerAI Companion.

JaegerAI owns agent identity, characters, and their persistence. ARES never
writes those files; it asks the independently versioned peer to read or mutate
them through bridge protocol v1.
"""
from __future__ import annotations

from typing import Any


class CompanionControlError(RuntimeError):
    """The selected JaegerAI Companion could not satisfy a control request."""


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _character_summary(value: Any) -> dict[str, Any]:
    row = _as_dict(value)
    return {
        "id": str(row.get("id") or ""),
        "name": str(row.get("name") or row.get("id") or ""),
        "role": str(row.get("role") or ""),
        "voice_tone": str(row.get("voice_tone") or ""),
        "voice_id": str(row.get("voice_id") or ""),
        "soul": str(row.get("soul") or ""),
        "backstory": str(row.get("backstory") or ""),
        "custom_instructions": str(row.get("custom_instructions") or ""),
        "active": bool(row.get("active")),
        "bound": bool(row.get("bound")),
    }


def companion_snapshot() -> dict[str, Any]:
    """Return the live identity and character exposed by JaegerAI."""
    try:
        from api.providers.jaeger.streaming import query_local_companion
        from api.providers.jaeger.paths import jaeger_home, jaeger_instance_name

        identity = _as_dict(query_local_companion("identity"))
        character = _as_dict(query_local_companion("character"))
        characters_raw = query_local_companion("characters")
        characters = [
            _character_summary(row)
            for row in (characters_raw if isinstance(characters_raw, list) else [])
        ]
        active_id = str(character.get("id") or "")
        active_summary = next((row for row in characters if row["id"] == active_id), {})
        return {
            "contract_version": 1,
            "dependency": {
                "product": "JaegerAI",
                "root": str(jaeger_home()),
                "transport": "bridge",
            },
            "agent": {
                "id": str(identity.get("instance") or jaeger_instance_name() or ""),
                "name": str(identity.get("agent_name") or ""),
                "model": identity.get("model"),
                "avatar": identity.get("avatar"),
            },
            "character": {
                **_character_summary(character),
                "active": bool(active_summary.get("active", True)),
                "bound": bool(active_summary.get("bound", False)),
                "custom_instructions": str(character.get("custom_instructions") or ""),
                "soul": str(character.get("soul") or ""),
                "backstory": str(character.get("backstory") or ""),
            },
            "characters": characters,
        }
    except Exception as exc:
        raise CompanionControlError(str(exc)) from exc


def companion_card(character_id: str | None = None) -> dict[str, Any] | None:
    """The card art for a character, as served by JaegerAI itself.

    Returns ``{"mime", "data" (base64), "bytes", "filename", "id"}`` or
    ``None`` when the peer has no art for that character.

    ARES does not read the image off disk: the path JaegerAI reports
    points inside its own install, and the ownership contract puts that
    directory out of bounds. The peer serves the bytes over the bridge
    instead, so this stays a normal cross-product query.

    Capability-negotiated, never version-sniffed: a runtime that does not
    declare the ``character_card`` query returns ``None`` here and the UI
    draws its own placeholder.
    """
    try:
        from api.providers.jaeger.streaming import (
            local_integration_contract,
            query_local_companion,
        )

        contract = local_integration_contract() or {}
        queries = ((contract.get("operations") or {}).get("queries") or [])
        if "character_card" not in queries:
            return None
        args = {"id": character_id.strip()} if character_id else {}
        art = query_local_companion("character_card", args)
    except Exception as exc:
        raise CompanionControlError(str(exc)) from exc
    if not isinstance(art, dict) or not art.get("data"):
        return None
    return {
        "id": str(art.get("id") or ""),
        "mime": str(art.get("mime") or "application/octet-stream"),
        "bytes": int(art.get("bytes") or 0),
        "filename": str(art.get("filename") or "card"),
        "data": str(art.get("data") or ""),
    }


def update_companion(
    *,
    name: str | None = None,
    character_id: str | None = None,
    custom_instructions: str | None = None,
    role: str | None = None,
    voice_tone: str | None = None,
    soul: str | None = None,
    backstory: str | None = None,
) -> dict[str, Any]:
    """Apply supported Companion edits through JaegerAI and read back truth."""
    clean_name = str(name or "").strip() if name is not None else None
    clean_character = str(character_id or "").strip() if character_id is not None else None
    if not any(
        v is not None
        for v in (clean_name, clean_character, custom_instructions, role, voice_tone, soul, backstory)
    ):
        raise CompanionControlError("No Companion changes were supplied.")
    try:
        from api.providers.jaeger.streaming import command_local_companion

        if clean_name:
            command_local_companion("save_identity", {"name": clean_name})
        if clean_character:
            # Selecting changes the live character now; binding makes the same
            # choice survive the next JaegerAI launch.
            command_local_companion("select_character", {"id": clean_character})
            command_local_companion("make_default", {"id": clean_character})

        profile_patch: dict[str, Any] = {}
        if custom_instructions is not None:
            profile_patch["custom_instructions"] = custom_instructions
        if role is not None:
            profile_patch["role"] = role
        if voice_tone is not None:
            profile_patch["voice_tone"] = voice_tone
        if soul is not None:
            profile_patch["soul"] = soul
        if backstory is not None:
            profile_patch["backstory"] = backstory

        if profile_patch:
            command_local_companion("save_profile", profile_patch)

        return companion_snapshot()
    except Exception as exc:
        raise CompanionControlError(str(exc)) from exc
