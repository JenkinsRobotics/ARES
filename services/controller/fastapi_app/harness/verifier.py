"""ARES Harness Deterministic Verifier & Subprocess Test Runner.

Steals Aider's compiler loopback and test execution runner to run
typechecks, builds, and unit tests in background subprocesses,
extracting actionable error diagnostics to feed into agent auto-remediation loops.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .linter import LintViolation


@dataclass
class VerificationStepResult:
    step_name: str
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    error_summary: Optional[str] = None
    extracted_errors: List[str] = field(default_factory=list)


class DeterministicVerifier:
    """Subprocess compiler and test execution verifier."""

    @classmethod
    async def run_process(
        cls,
        cmd: str,
        cwd: str,
        timeout_sec: float = 60.0,
    ) -> VerificationStepResult:
        """Run a shell command asynchronously and capture outputs."""
        if not os.path.isdir(cwd):
            return VerificationStepResult(
                step_name=cmd,
                passed=False,
                exit_code=1,
                stdout="",
                stderr=f"Directory does not exist: {cwd}",
                error_summary=f"CWD not found: {cwd}",
            )

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_sec
            )
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
            exit_code = proc.returncode or 0
            passed = exit_code == 0

            extracted = cls._extract_compiler_errors(stdout + "\n" + stderr)
            error_summary = None if passed else (extracted[0] if extracted else (stderr.strip() or stdout.strip()))

            return VerificationStepResult(
                step_name=cmd,
                passed=passed,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                error_summary=error_summary,
                extracted_errors=extracted,
            )
        except asyncio.TimeoutError:
            return VerificationStepResult(
                step_name=cmd,
                passed=False,
                exit_code=124,
                stdout="",
                stderr=f"Process timed out after {timeout_sec} seconds",
                error_summary=f"Execution timed out after {timeout_sec}s",
            )
        except Exception as e:
            return VerificationStepResult(
                step_name=cmd,
                passed=False,
                exit_code=1,
                stdout="",
                stderr=str(e),
                error_summary=f"Execution exception: {str(e)}",
            )

    @classmethod
    def _extract_compiler_errors(cls, raw_output: str) -> List[str]:
        """Extract clean compiler error lines (TypeScript, Python, Vitest)."""
        errors = []
        # TypeScript / Vite pattern: src/file.tsx:12:34 - error TS2322: Type '...'
        ts_pattern = re.compile(r"([a-zA-Z0-9_\-./]+\.[jt]sx?:\d+:\d+ - error TS\d+: [^\n]+)")
        for match in ts_pattern.finditer(raw_output):
            errors.append(match.group(1).strip())

        # Vitest / Jest pattern: FAIL src/file.test.ts > suite > test name
        vitest_pattern = re.compile(r"(FAIL\s+[^\n]+|AssertionError:[^\n]+|Error:\s+expect\([^\n]+)")
        for match in vitest_pattern.finditer(raw_output):
            errors.append(match.group(1).strip())

        # Python traceback pattern: File "...", line ..., in ...
        py_pattern = re.compile(r'(File "[^"]+", line \d+, in [^\n]+(?:\n\s+[^\n]+)*\n\s*(?:[A-Z][a-zA-Z0-9_]*Error:[^\n]+))')
        for match in py_pattern.finditer(raw_output):
            errors.append(match.group(1).strip())

        return errors

    @classmethod
    def format_remediation_prompt(
        cls,
        task_description: str,
        linter_violations: List[LintViolation],
        step_results: List[VerificationStepResult],
    ) -> str:
        """Format an unambiguous, actionable remediation prompt for the worker agent."""
        blocks = [
            f"### Deterministic Verification Gate Failed for: {task_description}",
            "Your previous code changes were rejected by the automated verifier. You must fix the following specific issues:\n",
        ]

        if linter_violations:
            blocks.append("#### Linter & Anti-Stub Violations (Fix Immediately):")
            for v in linter_violations:
                blocks.append(
                    f"- **[{v.rule}]** `{v.file}:{v.line_number}`: {v.message}\n"
                    f"  ```\n  {v.snippet}\n  ```"
                )
            blocks.append("")

        failed_steps = [s for s in step_results if not s.passed]
        if failed_steps:
            blocks.append("#### Compiler / Test Execution Failures:")
            for s in failed_steps:
                blocks.append(f"- **Command:** `{s.step_name}` (Exit Code: {s.exit_code})")
                if s.extracted_errors:
                    blocks.append("  **Specific Errors:**")
                    for err in s.extracted_errors[:5]:
                        blocks.append(f"  ```\n  {err}\n  ```")
                elif s.error_summary:
                    blocks.append(f"  ```\n  {s.error_summary}\n  ```")
            blocks.append("")

        blocks.append("Respond with corrected, complete code changes. Do NOT leave stubs, TODOs, or empty handlers.")
        return "\n".join(blocks)
