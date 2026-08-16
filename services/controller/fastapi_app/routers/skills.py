"""Profile-scoped skill catalog endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from api.skills_store import SkillStoreError
from api.runtime_skills import RuntimeSkillError

from ..errors import CoreApiError
from ..request_context import RequestIdentity, profile_scope, require_identity, require_mutation_identity


router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillSave(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=128)
    content: str = Field(max_length=2_000_000)
    category: str = Field(default="", max_length=128)


class SkillName(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=128)


class SkillToggle(SkillName):
    enabled: bool


def _error(exc: SkillStoreError) -> CoreApiError:
    return CoreApiError(exc.status_code, str(exc))


def _runtime_error(exc: RuntimeSkillError) -> CoreApiError:
    return CoreApiError(exc.status_code, str(exc))


@router.get("")
def skills(
    identity: Annotated[RequestIdentity, Depends(require_identity)],
    category: str | None = Query(default=None, max_length=128),
):
    from api.runtime_skills import list_runtime_skills, selected_runtime_owns_skills
    from api.skills_store import list_skills

    try:
        with profile_scope(identity.profile):
            return list_runtime_skills(category) if selected_runtime_owns_skills() else list_skills(category)
    except RuntimeSkillError as exc:
        raise _runtime_error(exc) from exc


@router.get("/usage")
def usage(identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.runtime_skills import runtime_skill_usage, selected_runtime_owns_skills
    from api.skills_store import skill_usage

    try:
        with profile_scope(identity.profile):
            return runtime_skill_usage() if selected_runtime_owns_skills() else skill_usage()
    except RuntimeSkillError as exc:
        raise _runtime_error(exc) from exc


@router.get("/content")
def content(
    identity: Annotated[RequestIdentity, Depends(require_identity)],
    name: str = Query(min_length=1, max_length=128),
    file: str | None = Query(default=None, max_length=1024),
):
    from api.runtime_skills import get_runtime_skill, selected_runtime_owns_skills
    from api.skills_store import skill_content

    try:
        with profile_scope(identity.profile):
            return get_runtime_skill(name, file) if selected_runtime_owns_skills() else skill_content(name, file)
    except SkillStoreError as exc:
        raise _error(exc) from exc
    except RuntimeSkillError as exc:
        raise _runtime_error(exc) from exc


@router.post("/save")
def save(payload: SkillSave, identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.runtime_skills import install_runtime_skill, selected_runtime_owns_skills
    from api.skills_store import save_skill

    try:
        with profile_scope(identity.profile):
            return (install_runtime_skill(payload.name, payload.content, payload.category)
                    if selected_runtime_owns_skills()
                    else save_skill(payload.name, payload.content, payload.category))
    except SkillStoreError as exc:
        raise _error(exc) from exc
    except RuntimeSkillError as exc:
        raise _runtime_error(exc) from exc


@router.post("/delete")
def delete(payload: SkillName, identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.runtime_skills import remove_runtime_skill, selected_runtime_owns_skills
    from api.skills_store import delete_skill

    try:
        with profile_scope(identity.profile):
            return (remove_runtime_skill(payload.name) if selected_runtime_owns_skills()
                    else delete_skill(payload.name))
    except SkillStoreError as exc:
        raise _error(exc) from exc
    except RuntimeSkillError as exc:
        raise _runtime_error(exc) from exc


@router.post("/toggle")
def toggle(payload: SkillToggle, identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.runtime_skills import selected_runtime_owns_skills, toggle_runtime_skill
    from api.skills_store import toggle_skill

    try:
        with profile_scope(identity.profile):
            return (toggle_runtime_skill(payload.name, payload.enabled)
                    if selected_runtime_owns_skills()
                    else toggle_skill(payload.name, payload.enabled))
    except SkillStoreError as exc:
        raise _error(exc) from exc
    except RuntimeSkillError as exc:
        raise _runtime_error(exc) from exc


@router.post("/clone")
def clone(payload: SkillName, identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.runtime_skills import clone_runtime_skill, selected_runtime_owns_skills

    try:
        with profile_scope(identity.profile):
            if not selected_runtime_owns_skills():
                raise RuntimeSkillError("Skill cloning is available only for a negotiated runtime", 409)
            return clone_runtime_skill(payload.name)
    except RuntimeSkillError as exc:
        raise _runtime_error(exc) from exc
