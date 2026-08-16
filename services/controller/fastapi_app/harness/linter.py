"""ARES Harness Diff Linter & Anti-Shortcut Governor.

Steals proven AST and regex inspection rules from SWE-agent and Aider
to deterministically catch placeholder stubs (console.log, TODO, pass, empty handlers)
before code is committed or presented to users.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class LintViolation:
    file: str
    line_number: int
    rule: str
    message: str
    snippet: str


@dataclass
class LintReport:
    passed: bool
    violations: List[LintViolation] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.passed:
            return "PASSED: 0 violations detected."
        items = [
            f"[{v.rule}] {v.file}:{v.line_number} -> {v.message}\n    Code: {v.snippet}"
            for v in self.violations
        ]
        return f"FAILED: {len(self.violations)} violations detected:\n" + "\n".join(items)


class DiffLinter:
    """Deterministic AST & Diff Linter for catching LLM shortcuts."""

    # Rules targeting placeholder shortcuts across JS/TS/Python
    PATTERNS = [
        (
            "NO_CONSOLE_LOG_STUB",
            re.compile(r"^\+.*console\.(log|warn|info)\s*\(\s*['\"`](?:stub|todo|branch|retry|click|handle|test|noop|debug)", re.IGNORECASE),
            "Unwired console.log placeholder detected. Implement active handler instead of logging.",
        ),
        (
            "NO_TODO_COMMENT",
            re.compile(r"^\+.*(?://|#|/\*)\s*(?:TODO|FIXME|XXX|HACK)\b", re.IGNORECASE),
            "Unresolved TODO/FIXME placeholder comment detected.",
        ),
        (
            "NO_EMPTY_HANDLER",
            re.compile(r"^\+.*(?:onClick|onBranch|onRetry|onSubmit|onChange)\s*=\s*(?:\{\s*\(\s*\)\s*=>\s*\{\s*\}|\(\)\s*=>\s*\{\s*\})"),
            "Empty callback / no-op arrow function handler detected.",
        ),
        (
            "NO_PYTHON_PASS_STUB",
            re.compile(r"^\+\s*(?:def|class)\s+[a-zA-Z0-9_]+\s*\(.*?\)\s*:\s*(?:pass|\.\.\.)\s*$"),
            "Empty Python function/class stub with 'pass' or '...' detected.",
        ),
        (
            "NO_NOT_IMPLEMENTED_STUB",
            re.compile(r"^\+\s*raise\s+NotImplementedError\b"),
            "Unimplemented function raising NotImplementedError detected.",
        ),
    ]

    @classmethod
    def inspect_diff(cls, diff_text: str) -> LintReport:
        """Inspect unified git diff text and return a LintReport."""
        violations: List[LintViolation] = []
        current_file = "unknown"
        line_num = 0

        for raw_line in diff_text.splitlines():
            # Track file header
            if raw_line.startswith("+++ b/"):
                current_file = raw_line[6:].strip()
                continue
            elif raw_line.startswith("+++ "):
                current_file = raw_line[4:].strip()
                continue

            # Track chunk line numbers: @@ -1,4 +1,5 @@
            if raw_line.startswith("@@"):
                match = re.search(r"\+(\d+)", raw_line)
                if match:
                    line_num = int(match.group(1)) - 1
                continue

            if raw_line.startswith("+") and not raw_line.startswith("+++"):
                line_num += 1
                stripped = raw_line[1:].strip()

                # Skip blank additions
                if not stripped:
                    continue

                for rule_id, pattern, message in cls.PATTERNS:
                    if pattern.search(raw_line):
                        violations.append(
                            LintViolation(
                                file=current_file,
                                line_number=line_num,
                                rule=rule_id,
                                message=message,
                                snippet=stripped,
                            )
                        )
            elif not raw_line.startswith("-"):
                line_num += 1

        return LintReport(passed=len(violations) == 0, violations=violations)

    @classmethod
    def inspect_python_syntax(cls, file_path: str, code: str) -> LintReport:
        """Inspect Python code for AST syntax validity."""
        violations: List[LintViolation] = []
        try:
            ast.parse(code, filename=file_path)
        except SyntaxError as err:
            violations.append(
                LintViolation(
                    file=file_path,
                    line_number=err.lineno or 1,
                    rule="PYTHON_SYNTAX_ERROR",
                    message=f"SyntaxError: {err.msg}",
                    snippet=err.text.strip() if err.text else "",
                )
            )
        return LintReport(passed=len(violations) == 0, violations=violations)
