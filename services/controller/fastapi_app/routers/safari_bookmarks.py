"""Privacy-preserving Safari bookmark operations.

Responses intentionally omit bookmark titles and URLs. Detailed review is a
local CLI responsibility; the model-facing API receives aggregate evidence.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..request_context import RequestIdentity, require_mutation_identity

router = APIRouter(prefix="/api/safari-bookmarks", tags=["safari-bookmarks"])


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proposal_id: str = Field(min_length=16, max_length=64)
    approval_token: str = Field(min_length=12, max_length=256)


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proposal_id: str = Field(min_length=16, max_length=64)
    approval_token: str = Field(min_length=12, max_length=256)


def _translate(callable_, *args):
    from api.safari_bookmarks import SafariBookmarkError
    try:
        return callable_(*args)
    except SafariBookmarkError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/audit")
def audit_bookmarks(
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.safari_bookmarks import create_proposal, public_summary
    proposal = _translate(create_proposal)
    return {
        "privacy": "local aggregate only; titles and URLs omitted",
        "proposal": public_summary(proposal),
        "approval_required": True,
        "next_step": "Review locally with `ares bookmarks review <proposal_id>`.",
    }


@router.post("/apply")
def apply_bookmarks(
    payload: ApplyRequest,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.safari_bookmarks import apply_proposal
    return {"proposal": _translate(apply_proposal, payload.proposal_id, payload.approval_token)}


@router.post("/rollback")
def rollback_bookmarks(
    payload: RollbackRequest,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.safari_bookmarks import rollback_proposal
    return {"proposal": _translate(rollback_proposal, payload.proposal_id, payload.approval_token)}


__all__ = ["router"]
