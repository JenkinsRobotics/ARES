"""ARES Harness Closed-Loop Orchestrator.

Manages the relentless feedback loop: intercepts agent turns, runs AST
linters and deterministic compilers, and re-prompts the worker with exact
failure diagnostics until 100% of requirements are verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Callable, Awaitable

from .linter import DiffLinter, LintReport, LintViolation
from .verifier import DeterministicVerifier, VerificationStepResult
from .schemas import FeatureRequirement, VerificationMatrix


@dataclass
class VerificationTurnResult:
    passed: bool
    linter_report: LintReport
    step_results: List[VerificationStepResult] = field(default_factory=list)
    remediation_prompt: Optional[str] = None


class HarnessOrchestrator:
    """Orchestrates deterministic verification gates and autonomous remediation loops."""

    @classmethod
    async def verify_diff(
        cls,
        task_description: str,
        diff_text: str,
        workspace_dir: Optional[str] = None,
        verification_commands: Optional[List[str]] = None,
    ) -> VerificationTurnResult:
        """Run all deterministic verification gates on a proposed git diff."""
        # 1. AST & No-Stub Diff Linter (fast gate: <5ms)
        linter_report = DiffLinter.inspect_diff(diff_text)
        step_results: List[VerificationStepResult] = []

        if not linter_report.passed:
            prompt = DeterministicVerifier.format_remediation_prompt(
                task_description=task_description,
                linter_violations=linter_report.violations,
                step_results=[],
            )
            return VerificationTurnResult(
                passed=False,
                linter_report=linter_report,
                step_results=[],
                remediation_prompt=prompt,
            )

        # 2. Subprocess Compiler / Test Gates (if workspace and commands provided)
        if workspace_dir and verification_commands:
            for cmd in verification_commands:
                res = await DeterministicVerifier.run_process(cmd=cmd, cwd=workspace_dir)
                step_results.append(res)
                if not res.passed:
                    prompt = DeterministicVerifier.format_remediation_prompt(
                        task_description=task_description,
                        linter_violations=[],
                        step_results=step_results,
                    )
                    return VerificationTurnResult(
                        passed=False,
                        linter_report=linter_report,
                        step_results=step_results,
                        remediation_prompt=prompt,
                    )

        return VerificationTurnResult(
            passed=True,
            linter_report=linter_report,
            step_results=step_results,
            remediation_prompt=None,
        )

    @classmethod
    async def run_matrix_loop(
        cls,
        matrix: VerificationMatrix,
        worker_turn_fn: Callable[[FeatureRequirement, Optional[str]], Awaitable[str]],
        workspace_dir: Optional[str] = None,
        verification_commands: Optional[List[str]] = None,
        max_attempts: int = 4,
    ) -> VerificationMatrix:
        """Execute a closed-loop progression across all matrix items."""
        matrix.overall_status = "in_progress"

        for item in matrix.items:
            if item.status == "verified":
                continue

            item.status = "in_progress"
            remediation_prompt = None

            for attempt in range(1, max_attempts + 1):
                item.attempts_count = attempt
                
                # Dispatch turn to worker (passes remediation prompt if retry)
                proposed_diff = await worker_turn_fn(item, remediation_prompt)

                # Verify proposed diff
                turn_result = await cls.verify_diff(
                    task_description=item.title,
                    diff_text=proposed_diff,
                    workspace_dir=workspace_dir,
                    verification_commands=verification_commands,
                )

                if turn_result.passed:
                    item.status = "verified"
                    item.failure_details = None
                    break
                else:
                    remediation_prompt = turn_result.remediation_prompt
                    item.failure_details = turn_result.linter_report.summary

            if item.status != "verified":
                item.status = "failed"
                matrix.overall_status = "failed"
                return matrix

        matrix.overall_status = "verified" if matrix.is_complete else "failed"
        return matrix
