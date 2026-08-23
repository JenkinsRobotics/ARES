"""Source guard for the ARES/Jaeger ownership boundary."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

_SCAN_ROOTS = (
    "core",
    "integrations",
    "services/controller",
    "apps/macos/Sources",
    "apps/web/static",
)
_SCAN_SUFFIXES = {".py", ".swift", ".js", ".html", ".css", ".sh", ".strings"}

# NOTE: the donor-identifier ban that used to live here has been removed.
# It forbade the substring "hermes" outside an allowlist, which made sense
# while the frontend was still an unrenamed hermes-webui fork. The rebrand
# moved all 69 storage keys and every internal global to `ares`, so the only
# remaining occurrences are ones that MUST stay: the third-party
# hermes-webui-desktop-companion extension's public hook, and the external
# Hermes agent that cross-agent memory imports from. A guard whose every hit
# is a false positive is one people learn to ignore.
#
# Provenance is recorded in THIRD_PARTY.md and enforced by
# test_attribution_is_intact.py, which is where it belongs — renaming symbols
# never discharged the MIT obligation anyway.

# Instance internals that must go through the shared resolver, plus the known
# developer homes. Matched case-sensitively.
#
# Deliberately NOT a blanket ban on `/Users/`, `/home/`, or `GitHub/`: all three
# appear legitimately in docstrings explaining path shapes, in i18n
# placeholders shown to the user ("/Users/you/Documents"), and in
# WebUIServerManager's list of common checkout layouts probed relative to
# $HOME. Banning them outright made this guard noisy, and a noisy guard gets
# ignored — which is how the eval-suite leak survived in the first place.
# `_absolute_home_paths_in_python_strings` below is the general rule that
# catches any contributor's home directory without the noise.
_FORBIDDEN_PATH_LITERALS = (
    ".jaeger_os",
    "/Users/matthewjenkins",
    "/Users/jonathanjenkins",
)

# An absolute home path used as a VALUE (not described in a comment) is the
# actual leak shape. For Python we can tell the difference precisely.
_ABSOLUTE_HOME_PATH = re.compile(r"^/(?:Users|home)/[^/]+/")

# Placeholder "usernames" that are illustrative rather than somebody's account.
_PLACEHOLDER_HOME_OWNERS = frozenset({
    "you", "user", "username", "me", "your-user", "yourname", "tu", "usuario",
})


def _runtime_sources():
    """Every runtime source file, excluding tests, dotfiles, and docs."""
    for root_name in _SCAN_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in _SCAN_SUFFIXES or not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            parts = relative.parts
            if "tests" in parts or "docs" in parts:
                continue
            if any(part.startswith(".") for part in parts):
                continue
            yield relative, path



def test_runtime_sources_do_not_hardcode_absolute_or_instance_paths():
    """No developer home directories, no hardcoded instance internals.

    Strict and universal: a path literal here ships to every user of a public
    repo, and either leaks the author's machine layout or silently bypasses
    the shared path resolver.
    """
    findings: list[str] = []
    for relative, path in _runtime_sources():
        text = path.read_text(encoding="utf-8")
        for literal in _FORBIDDEN_PATH_LITERALS:
            if literal in text:
                findings.append(f"{relative}: {literal}")
    assert findings == [], (
        "Paths must go through the shared resolver, and no absolute path may "
        "be hardcoded:\n" + "\n".join(findings)
    )


def _absolute_home_paths_in_python_strings(path: Path) -> list[str]:
    """String constants that are an absolute path into somebody's home.

    AST-based so a docstring describing `/Users/you/Documents` is invisible
    while `Path("/Users/alice/GitHub/ARES/out.json")` is caught, for any
    contributor rather than a hardcoded list of names.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if node in docstrings:
            continue
        match = _ABSOLUTE_HOME_PATH.match(node.value)
        if match is None:
            continue
        owner = node.value.split("/")[2]
        if owner.lower() in _PLACEHOLDER_HOME_OWNERS:
            continue
        found.append(f"line {node.lineno}: {node.value}")
    return found


def test_python_sources_never_build_paths_from_a_real_home_directory():
    """The general form of the eval-suite leak, for any contributor.

    ``core/evaluation/eval_suite.py`` shipped
    ``Path("/Users/<author>/GitHub/ARES/model_eval_results.json")`` as a
    best-effort mirror write. Nothing read it, the exception was swallowed, and
    the guard that should have caught it was drowning in false positives.
    """
    findings: list[str] = []
    for relative, path in _runtime_sources():
        if path.suffix != ".py":
            continue
        for hit in _absolute_home_paths_in_python_strings(path):
            findings.append(f"{relative}: {hit}")
    assert findings == [], (
        "Absolute home-directory path in a string value — derive it from "
        "ARES_HOME, the shared resolver, or a config value instead:\n"
        + "\n".join(findings)
    )




def test_provider_compat_has_no_persona_or_secret_store_hardcodes():
    source = (ROOT / "services/controller/fastapi_app/routers/provider_compat.py").read_text(
        encoding="utf-8")
    for forbidden in ("jarvis", ".jaeger_os", "GitHub/JaegerAI", ".hermes"):
        assert forbidden not in source.lower()


def test_ares_never_reads_jaeger_credentials_or_mcp_files_directly():
    boundary_files = [
        ROOT / "services/controller/api/runtime_credentials.py",
        ROOT / "services/controller/api/runtime_mcp.py",
        ROOT / "services/controller/fastapi_app/routers/provider_compat.py",
        ROOT / "integrations/providers/ollama/context_probe.py",
    ]
    forbidden = (
        ".jaeger_ai",
        "mcp.json",
        "credentials_dir",
        "_read_jaeger_credential",
        "ARES_SESSION_DIR",
    )
    findings = []
    for path in boundary_files:
        source = path.read_text(encoding="utf-8")
        for literal in forbidden:
            if literal in source:
                findings.append(f"{path.relative_to(ROOT)}: {literal}")
    assert findings == [], (
        "Jaeger-owned state must be accessed through bridge services:\n"
        + "\n".join(findings)
    )
