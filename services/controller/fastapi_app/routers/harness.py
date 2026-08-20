"""FastAPI Router for ARES Verification Harness & Autonomous Governor."""

from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fastapi_app.harness.linter import DiffLinter
from fastapi_app.harness.verifier import DeterministicVerifier
from fastapi_app.harness.orchestrator import HarnessOrchestrator
from fastapi_app.harness.extractor import FeatureExtractor
from fastapi_app.harness.schemas import FeatureRequirement, VerificationMatrix

router = APIRouter(prefix="/api/harness", tags=["harness"])


class VerifyDiffRequest(BaseModel):
    task_description: str
    diff_text: str
    workspace_dir: Optional[str] = None
    verification_commands: Optional[List[str]] = None


class VerifyDiffResponse(BaseModel):
    passed: bool
    linter_summary: str
    remediation_prompt: Optional[str] = None
    violations_count: int


@router.post("/verify-diff", response_model=VerifyDiffResponse)
async def verify_diff_endpoint(req: VerifyDiffRequest):
    """Verify a proposed git diff against AST anti-stub rules and optional subprocess tests."""
    result = await HarnessOrchestrator.verify_diff(
        task_description=req.task_description,
        diff_text=req.diff_text,
        workspace_dir=req.workspace_dir,
        verification_commands=req.verification_commands,
    )
    return VerifyDiffResponse(
        passed=result.passed,
        linter_summary=result.linter_report.summary,
        remediation_prompt=result.remediation_prompt,
        violations_count=len(result.linter_report.violations),
    )


@router.get("/matrix/chat-parity", response_model=VerificationMatrix)
async def get_chat_parity_matrix():
    """Retrieve the standard Legacy WebUI parity parity verification matrix."""
    return FeatureExtractor.decompose_chat_parity_task()


class CreateMatrixRequest(BaseModel):
    task_description: str
    items: List[dict]


@router.post("/matrix/create", response_model=VerificationMatrix)
async def create_matrix_endpoint(req: CreateMatrixRequest):
    """Create a custom VerificationMatrix from task requirements."""
    return FeatureExtractor.create_from_items(
        task_description=req.task_description,
        items_data=req.items,
    )
