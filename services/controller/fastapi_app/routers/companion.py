"""ARES-owned API projection of the selected JaegerAI Companion."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ..errors import CoreApiError
from ..request_context import (
    RequestIdentity,
    profile_scope,
    require_identity,
    require_mutation_identity,
)

router = APIRouter(prefix="/api/companion", tags=["companion"])


class CompanionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    character_id: str | None = Field(default=None, min_length=1, max_length=128)
    owner_name: str | None = Field(default=None, max_length=120)
    custom_instructions: str | None = Field(default=None, max_length=50000)
    role: str | None = Field(default=None, max_length=5000)
    voice_tone: str | None = Field(default=None, max_length=5000)
    soul: str | None = Field(default=None, max_length=10000)
    backstory: str | None = Field(default=None, max_length=10000)


def _snapshot() -> dict[str, Any]:
    from api.providers.jaeger.companion_control import (
        CompanionControlError,
        companion_snapshot,
    )

    try:
        return companion_snapshot()
    except CompanionControlError as exc:
        raise CoreApiError(
            503,
            f"JaegerAI Companion is unavailable: {exc}",
            code="companion_unavailable",
        ) from exc


def _with_relationship(snapshot: dict[str, Any]) -> dict[str, Any]:
    from api.config import load_settings

    settings = load_settings() or {}
    ares_name = str(settings.get("bot_name") or "").strip()
    jaeger_name = str((snapshot.get("agent") or {}).get("name") or "").strip()
    return {
        **snapshot,
        "relationship": {
            "owner_name": str(settings.get("owner_name") or "").strip(),
            "ares_name": ares_name,
            "aligned": bool(ares_name and jaeger_name and ares_name == jaeger_name),
        },
    }


@router.get("")
def get_companion(
    identity: Annotated[RequestIdentity, Depends(require_identity)],
) -> dict[str, Any]:
    with profile_scope(identity.profile):
        return _with_relationship(_snapshot())


@router.patch("")
def patch_companion(
    payload: CompanionUpdate,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
) -> dict[str, Any]:
    from api.providers.jaeger.companion_control import CompanionControlError, update_companion
    from fastapi_app.routers.ares import save_config_values

    clean_name = payload.name.strip() if payload.name is not None else None
    clean_character = payload.character_id.strip() if payload.character_id is not None else None
    clean_owner = payload.owner_name.strip() if payload.owner_name is not None else None
    if payload.name is not None and not clean_name:
        raise CoreApiError(400, "Companion name cannot be blank.", code="invalid_companion_name")
    if payload.character_id is not None and not clean_character:
        raise CoreApiError(400, "Character cannot be blank.", code="invalid_companion_character")
    if not any(
        value is not None
        for value in (
            clean_name,
            clean_character,
            clean_owner,
            payload.custom_instructions,
            payload.role,
            payload.voice_tone,
            payload.soul,
            payload.backstory,
        )
    ):
        raise CoreApiError(400, "No Companion changes were supplied.", code="empty_companion_update")

    with profile_scope(identity.profile):
        try:
            snapshot = update_companion(
                name=clean_name,
                character_id=clean_character,
                custom_instructions=payload.custom_instructions,
                role=payload.role,
                voice_tone=payload.voice_tone,
                soul=payload.soul,
                backstory=payload.backstory,
            )
        except CompanionControlError as exc:
            raise CoreApiError(
                503,
                f"JaegerAI rejected the Companion update: {exc}",
                code="companion_update_failed",
            ) from exc

        settings_patch: dict[str, Any] = {}
        if clean_name:
            # ARES owns the continuous product identity; JaegerAI stores the
            # matching runtime projection through its validated command.
            settings_patch["bot_name"] = clean_name
        if clean_owner is not None:
            settings_patch["owner_name"] = clean_owner
        if settings_patch:
            from api.config import save_settings

            save_settings(settings_patch)
        # Saving this relationship is the explicit user action that elects
        # JaegerAI as ARES's primary local runtime. Controller runtime choices
        # live in config.yaml, separate from profile settings.json.
        save_config_values({"ares_backend": "jaeger_local"})
        return _with_relationship(snapshot)
