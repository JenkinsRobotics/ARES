"""Jaeger character projection through the owner bridge."""
from __future__ import annotations

from typing import Any, Optional


def _query(what: str, args: dict[str, Any] | None = None) -> Any:
    from api.providers.jaeger.streaming import query_local_companion

    return query_local_companion(what, args or {})


def list_personas() -> list[dict[str, str]]:
    try:
        rows = _query("characters")
    except Exception:
        return []
    return [
        {
            "id": str(row.get("id") or ""),
            "name": str(row.get("name") or row.get("id") or ""),
            "description": str(row.get("role") or "")[:120],
            "schema": "jaeger/character",
        }
        for row in rows if isinstance(row, dict) and row.get("id")
    ] if isinstance(rows, list) else []


def load_persona(persona_id: str) -> Optional[dict[str, Any]]:
    try:
        row = _query("character", {"id": str(persona_id or "").strip()})
    except Exception:
        return None
    if not isinstance(row, dict):
        return None
    return {
        "schema": "jaeger/character",
        "id": str(row.get("id") or persona_id),
        "name": str(row.get("name") or persona_id),
        "description": str(row.get("role") or "")[:120],
        "identity": {
            "display_name": str(row.get("name") or ""),
            "role": str(row.get("role") or ""),
            "voice_tone": str(row.get("voice_tone") or ""),
            "voice_id": str(row.get("voice_id") or ""),
        },
        "custom_instructions": str(row.get("custom_instructions") or ""),
        "soul": str(row.get("soul") or ""),
        "backstory": str(row.get("backstory") or ""),
        "speech_patterns": list(row.get("speech_patterns") or []),
    }


def render_persona_prompt(persona: dict[str, Any]) -> str:
    identity = persona.get("identity") if isinstance(persona.get("identity"), dict) else {}
    parts = [str(persona.get("custom_instructions") or "").strip()]
    if not parts[0] and identity.get("display_name"):
        parts[0] = f"You are {identity['display_name']}."
    if identity.get("role"):
        parts.append(f"Your role: {identity['role']}")
    if identity.get("voice_tone"):
        parts.append(f"Voice tone: {identity['voice_tone']}")
    patterns = "; ".join(str(value) for value in persona.get("speech_patterns", [])[:5] if value)
    if patterns:
        parts.append(f"Speech patterns: {patterns}")
    if persona.get("soul"):
        parts.append(str(persona["soul"]))
    return "\n\n".join(part for part in parts if part)


def get_persona_prompt(persona_id: Optional[str]) -> str:
    persona = load_persona(str(persona_id or "").strip()) if persona_id else None
    return render_persona_prompt(persona) if persona else ""
