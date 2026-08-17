"""Research ingestion and generated-artifact HTTP contracts."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ..errors import CoreApiError
from ..request_context import RequestIdentity, profile_scope, require_identity, require_mutation_identity


router = APIRouter(prefix="/api/content", tags=["content"])


class WorkspaceFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    session_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    path: str = Field(min_length=1, max_length=2048)


class PdfFill(WorkspaceFile):
    fields: dict[str, Any]


class YouTubeIngest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    session_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    url: str = Field(min_length=1, max_length=2048)
    languages: list[str] = Field(default_factory=lambda: ["en.*", "en"], max_length=5)


class ImageEdit(WorkspaceFile):
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=10)


class VisualReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    session_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=20_000)
    sections: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


def _call(profile: str | None, operation, *args, **kwargs):
    from api.generated_artifacts import GeneratedArtifactError
    from api.ingestion import IngestionError
    from api.workspace_artifacts import ArtifactError

    try:
        with profile_scope(profile):
            return operation(*args, **kwargs)
    except (ArtifactError, GeneratedArtifactError, IngestionError) as exc:
        raise CoreApiError(exc.status_code, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise CoreApiError(400, str(exc)) from exc


@router.post("/pdf/extract")
def pdf_extract(payload: WorkspaceFile, identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.ingestion import extract_pdf

    return _call(identity.profile, extract_pdf, payload.session_id, payload.path)


@router.post("/pdf/fill")
def pdf_fill(payload: PdfFill, identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.ingestion import fill_pdf_form

    return _call(identity.profile, fill_pdf_form, payload.session_id, payload.path, payload.fields)


@router.post("/youtube/ingest")
def youtube_ingest(payload: YouTubeIngest, identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.ingestion import ingest_youtube

    return _call(identity.profile, ingest_youtube, payload.session_id, payload.url, payload.languages)


@router.get("/artifacts/{session_id}")
def artifacts(
    session_id: str,
    identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    from api.workspace_artifacts import list_artifacts

    return _call(identity.profile, list_artifacts, session_id)


@router.get("/gallery/{session_id}")
def image_gallery(
    session_id: str,
    identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    from api.generated_artifacts import gallery

    return _call(identity.profile, gallery, session_id)


@router.post("/image/edit")
def image_edit(payload: ImageEdit, identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.generated_artifacts import edit_image

    return _call(identity.profile, edit_image, payload.session_id, payload.path, payload.operations)


@router.post("/reports")
def visual_report(payload: VisualReport, identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    from api.generated_artifacts import create_visual_report

    return _call(
        identity.profile,
        create_visual_report,
        payload.session_id,
        title=payload.title,
        summary=payload.summary,
        sections=payload.sections,
    )


__all__ = ["router"]
