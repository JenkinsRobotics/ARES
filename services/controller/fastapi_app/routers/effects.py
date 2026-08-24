"""Proxy for JaegerAI effect-ledger settlement. ARES does not own the rows."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ..errors import CoreApiError
from ..request_context import RequestIdentity, require_identity, require_mutation_identity


router = APIRouter(prefix="/api/effects", tags=["effects"])


class EffectKey(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(min_length=1, max_length=512)
    result: Any = None


def _query(what: str, args: dict[str, Any] | None = None) -> Any:
    try:
        from api.providers.jaeger.streaming import query_local_companion
        return query_local_companion(what, args or {})
    except Exception as exc:  # noqa: BLE001 — runtime may be down
        raise CoreApiError(503, str(exc) or "JaegerAI runtime unavailable") from exc


def _command(cmd: str, args: dict[str, Any]) -> Any:
    try:
        from api.providers.jaeger.streaming import command_local_companion
        return command_local_companion(cmd, args)
    except Exception as exc:  # noqa: BLE001
        raise CoreApiError(503, str(exc) or "JaegerAI runtime unavailable") from exc


@router.get("")
async def list_effects(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
) -> dict[str, Any]:
    rows = _query("list_effects", {"status": "pending"})
    if not isinstance(rows, list):
        rows = []
    return {"owner": "jaeger", "effects": rows}


@router.post("/resolve")
async def resolve_effect(
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
    body: EffectKey,
) -> dict[str, Any]:
    result = _command("resolve_effect", {"key": body.key, "result": body.result})
    return {"ok": True, "result": result}


@router.post("/abandon")
async def abandon_effect(
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
    body: EffectKey,
) -> dict[str, Any]:
    result = _command("abandon_effect", {"key": body.key})
    return {"ok": True, "result": result}
