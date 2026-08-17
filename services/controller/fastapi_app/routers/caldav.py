"""Authenticated, profile-scoped CalDAV API."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from api.caldav_service import CalDavError
from api.secret_vault import SecretVaultError
from ..errors import CoreApiError
from ..request_context import (
    RequestIdentity,
    require_identity,
    require_mutation_identity,
)


router = APIRouter(prefix="/api/caldav", tags=["caldav"])


class CalDavConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    calendar_url: str = Field(min_length=1, max_length=2048)
    username: str = Field(min_length=1, max_length=512)
    password: str | None = Field(default=None, min_length=1, max_length=100_000)


class CalDavEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    uid: str | None = Field(default=None, max_length=255)
    summary: str = Field(min_length=1, max_length=1024)
    description: str = Field(default="", max_length=100_000)
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(min_length=1, max_length=64)
    etag: str | None = Field(default=None, max_length=1024)


class CalDavDelete(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    uid: str = Field(min_length=1, max_length=255)
    etag: str | None = Field(default=None, max_length=1024)


def _error(exc: Exception) -> CoreApiError:
    return CoreApiError(getattr(exc, "status_code", 503), str(exc))


async def _call(operation, *args, **kwargs):
    try:
        return await asyncio.to_thread(operation, *args, **kwargs)
    except (CalDavError, SecretVaultError) as exc:
        raise _error(exc) from exc


@router.get("/config")
def config(identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.caldav_service import get_config

    return get_config(identity.profile)


@router.put("/config")
async def update_config(
    payload: CalDavConfig,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.caldav_service import configure

    return await _call(configure, identity.profile, **payload.model_dump())


@router.get("/events")
def events(identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.caldav_service import list_cached_events

    return list_cached_events(identity.profile)


@router.post("/sync")
async def synchronize(
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.caldav_service import sync

    return await _call(sync, identity.profile)


@router.put("/events")
async def save_event(
    payload: CalDavEvent,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.caldav_service import put_event

    return await _call(put_event, identity.profile, **payload.model_dump())


@router.delete("/events")
async def remove_event(
    payload: CalDavDelete,
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.caldav_service import delete_event

    return await _call(delete_event, identity.profile, **payload.model_dump())


__all__ = ["router"]
