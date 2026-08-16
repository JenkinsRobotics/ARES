import pytest
import os
from fastapi_app.harness.verifier import DeterministicVerifier, VerificationStepResult
from fastapi_app.harness.linter import LintViolation

@pytest.mark.asyncio
async def test_run_process_success(tmp_path):
    res = await DeterministicVerifier.run_process("echo 'hello world'", cwd=str(tmp_path))
    assert res.passed is True
    assert res.exit_code == 0
    assert "hello world" in res.stdout

@pytest.mark.asyncio
async def test_run_process_failure(tmp_path):
    res = await DeterministicVerifier.run_process("sh -c 'echo \"failed step\" >&2; exit 2'", cwd=str(tmp_path))
    assert res.passed is False
    assert res.exit_code == 2
    assert "failed step" in res.stderr

def test_extract_ts_errors():
    raw = """
src/features/chat/ConversationPage.tsx:124:18 - error TS2322: Type 'string' is not assignable to type 'number'.
  124 const value: number = "bad";
                            ~~~~~
Found 1 error in src/features/chat/ConversationPage.tsx:124
"""
    extracted = DeterministicVerifier._extract_compiler_errors(raw)
    assert len(extracted) == 1
    assert "TS2322: Type 'string' is not assignable to type 'number'" in extracted[0]

def test_format_remediation_prompt():
    violations = [
        LintViolation(
            file="ConversationPage.tsx",
            line_number=756,
            rule="NO_CONSOLE_LOG_STUB",
            message="Unwired console.log placeholder",
            snippet="onBranch: () => console.log('stub')",
        )
    ]
    step_results = [
        VerificationStepResult(
            step_name="npm run typecheck",
            passed=False,
            exit_code=2,
            stdout="src/file.tsx:10:5 - error TS2304: Cannot find name 'badVar'.",
            stderr="",
            extracted_errors=["src/file.tsx:10:5 - error TS2304: Cannot find name 'badVar'."],
        )
    ]
    prompt = DeterministicVerifier.format_remediation_prompt(
        "Port model accordion", violations, step_results
    )
    assert "Deterministic Verification Gate Failed for: Port model accordion" in prompt
    assert "NO_CONSOLE_LOG_STUB" in prompt
    assert "ConversationPage.tsx:756" in prompt
    assert "npm run typecheck" in prompt
    assert "TS2304: Cannot find name 'badVar'" in prompt
