"""Capability-owned model intelligence endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from api.model_intelligence import ModelIntelligenceError
from ..errors import CoreApiError
from ..request_context import (
    RequestIdentity,
    require_identity,
    require_mutation_identity,
)


router = APIRouter(prefix="/api/model-intelligence", tags=["model-intelligence"])


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    backend: str = Field(min_length=1, max_length=128)
    model: str | None = Field(default=None, max_length=512)
    provider: str | None = Field(default=None, max_length=128)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prompt: str = Field(min_length=1, max_length=100_000)
    targets: list[Target] = Field(min_length=2, max_length=4)


class TeacherRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prompt: str = Field(min_length=1, max_length=100_000)
    primary: Target
    teacher: Target


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except ModelIntelligenceError as exc:
        raise CoreApiError(exc.status_code, str(exc)) from exc


@router.get("")
def get_inventory(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
) -> dict[str, Any]:
    from api.model_intelligence import inventory

    return inventory()


@router.get("/history")
def get_history(identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.model_intelligence import history

    return history(identity.profile)


@router.post("/compare")
def run_compare(
    payload: CompareRequest,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.model_intelligence import compare

    return _call(
        compare,
        identity.profile,
        prompt=payload.prompt,
        targets=[item.model_dump() for item in payload.targets],
    )


@router.post("/teacher")
def run_teacher(
    payload: TeacherRequest,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.model_intelligence import teacher_escalation

    return _call(
        teacher_escalation,
        identity.profile,
        prompt=payload.prompt,
        primary=payload.primary.model_dump(),
        teacher=payload.teacher.model_dump(),
    )


__all__ = ["router"]
