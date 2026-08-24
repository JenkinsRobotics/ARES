"""Read-only Jaeger runtime projection plus explicit event delivery."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ..errors import CoreApiError
from ..request_context import RequestIdentity, require_identity, require_mutation_identity

router = APIRouter(prefix="/api/jaeger-runtime", tags=["jaeger-runtime"])


def _query(what: str, args: dict[str, Any] | None = None) -> Any:
    try:
        from api.providers.jaeger.streaming import query_local_companion
        return query_local_companion(what, args or {})
    except Exception as exc:
        raise CoreApiError(503, str(exc) or "JaegerAI runtime unavailable") from exc


def _command(cmd: str, args: dict[str, Any]) -> Any:
    try:
        from api.providers.jaeger.streaming import command_local_companion
        return command_local_companion(cmd, args)
    except Exception as exc:
        raise CoreApiError(503, str(exc) or "JaegerAI runtime unavailable") from exc


class WakeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    wake_key: str = Field(min_length=1, max_length=512)


@router.get("")
async def runtime_projection(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
) -> dict[str, Any]:
    commitments = _query("list_commitments")
    runs = _query("list_runs")
    return {
        "owner": "jaeger",
        "commitments": commitments if isinstance(commitments, list) else [],
        "runs": runs if isinstance(runs, list) else [],
    }


@router.post("/deliver-event")
async def deliver_event(
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
    body: WakeEvent,
) -> dict[str, Any]:
    return {"ok": True, "result": _command("deliver_event", {"wake_key": body.wake_key})}
