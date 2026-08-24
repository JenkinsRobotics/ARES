"""Jaeger character details projected through the owner bridge."""
from __future__ import annotations

from typing import Any, Optional


def _query(what: str, args: dict[str, Any] | None = None) -> Any:
    from api.providers.jaeger.streaming import query_local_companion

    return query_local_companion(what, args or {})


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    lore = {
        "quotes": [],
        "mannerisms": [],
        "ideals": [],
        "behaviors": [],
        **dict(row.get("lore") or {}),
    }
    return {
        "id": str(row.get("id") or ""),
        "name": str(row.get("name") or row.get("id") or ""),
        "description": str(row.get("role") or ""),
        "role": str(row.get("role") or ""),
        "voice_tone": str(row.get("voice_tone") or ""),
        "voice_id": str(row.get("voice_id") or ""),
        "soul": str(row.get("soul") or ""),
        "level": int(row.get("level") or 1),
        "revision": float(row.get("revision") or 1.0),
        "card_url": row.get("card") or row.get("icon") or "/assets/ares-app-icon.png",
        "traits": dict(row.get("traits") or {}),
        "lore": lore,
        "custom_instructions": str(row.get("custom_instructions") or ""),
        "backstory": str(row.get("backstory") or ""),
        "speech_patterns": list(row.get("speech_patterns") or []),
    }


def list_characters() -> list[dict[str, Any]]:
    try:
        rows = _query("characters")
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    projected: list[dict[str, Any]] = []
    for summary in rows:
        if not isinstance(summary, dict):
            continue
        row = dict(summary)
        char_id = str(row.get("id") or "")
        if char_id:
            try:
                detail = _query("character", {"id": char_id})
            except Exception:
                detail = None
            if isinstance(detail, dict):
                row.update(detail)
        projected.append(_normalize(row))
    return projected


def get_character(char_id: str) -> Optional[dict[str, Any]]:
    try:
        row = _query("character", {"id": str(char_id or "").strip()})
    except Exception:
        return None
    return _normalize(row) if isinstance(row, dict) else None
