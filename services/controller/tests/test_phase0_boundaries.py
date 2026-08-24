"""Architecture boundaries Phase 0 established. Minimum set, deliberately.

Each of these pins a property that a Phase 0 finding showed was NOT holding,
and each fails loudly rather than drifting. They are cheap, static, and need
no server, no network and no credentials — so they can sit in the fast gate.

Kept small on purpose: this is not the future architecture-enforcement suite,
only the handful of rules that had to become non-negotiable before any
restructuring starts.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTROLLER = REPO_ROOT / "services" / "controller"


def _python_files(*roots: Path):
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            yield path


# ── ARES must not reach into JaegerAI's internals ──────────────────────


def test_ares_does_not_import_jaeger_runtime_internals():
    """The bridge protocol is the boundary; Python imports are not.

    ARES drives JaegerAI by spawning ``jaeger bridge`` and speaking v1 NDJSON
    over stdio — ``bridge_client.py`` says "stdlib only: no JaegerAI package is
    imported into ARES" and means it. Importing ``jaeger_ai.*`` or
    ``jaeger_os.*`` would couple the two products' release cycles and make the
    wire contract decorative.
    """
    offenders: list[str] = []
    for path in _python_files(REPO_ROOT / "core", REPO_ROOT / "integrations",
                              CONTROLLER / "api", CONTROLLER / "fastapi_app"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if root in {"jaeger_ai", "jaeger_os", "jaeger_agent"}:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {name}")
    assert offenders == [], (
        "ARES must drive JaegerAI over the bridge protocol, not by import:\n"
        + "\n".join(offenders)
    )


# ── the SI pipeline must not become authoritative by accident ──────────


def test_an_explicit_disable_always_wins():
    """``core/si`` is 3,616 lines of wired-but-flag-gated pipeline.

    It is EXPERIMENTAL until someone decides otherwise, and turning it OFF must
    be absolute — an operator who disables it cannot have settings.json quietly
    turn it back on, or every chat turn moves to an unevaluated path without
    anyone choosing that.

    Only explicit spellings are asserted. An EMPTY value is documented as
    "unset" and deliberately defers to settings, so testing it here would make
    this assertion depend on whatever the machine happens to have configured —
    the same environment-coupling Phase 0 exists to remove.
    """
    from core.si.bridge import si_enabled

    for value in ("0", "false", "FALSE", "no", "off", " off "):
        os.environ["ARES_SI_ENABLED"] = value
        try:
            assert si_enabled() is False, f"an explicit {value!r} did not disable SI"
        finally:
            os.environ.pop("ARES_SI_ENABLED", None)


def test_enabling_si_is_possible_so_the_guard_above_means_something():
    """Without this, a broken ``si_enabled`` would satisfy the test above."""
    from core.si.bridge import si_enabled

    for value in ("1", "true", "YES", "on"):
        os.environ["ARES_SI_ENABLED"] = value
        try:
            assert si_enabled() is True, f"an explicit {value!r} did not enable SI"
        finally:
            os.environ.pop("ARES_SI_ENABLED", None)


def test_the_code_default_is_off_when_nothing_is_configured():
    """Priority 3 — the fallback with no env and no settings key.

    Patched rather than read from disk: the real answer depends on the
    operator's settings.json, and what needs pinning is the DEFAULT, not this
    machine's configuration.
    """
    import core.si.bridge as si_bridge

    import sys

    os.environ.pop("ARES_SI_ENABLED", None)

    class _NoSettings:
        @staticmethod
        def load_settings():
            return {}

    saved = sys.modules.get("api.config")
    sys.modules["api.config"] = _NoSettings  # type: ignore[assignment]
    try:
        assert si_bridge.si_enabled() is False, (
            "with no env and no settings key, SI must default to OFF"
        )
    finally:
        if saved is not None:
            sys.modules["api.config"] = saved
        else:
            sys.modules.pop("api.config", None)


# ── ctl.sh must not stop processes it does not own ─────────────────────


def test_ctl_ownership_check_is_scoped_to_this_install():
    """Phase 0 root cause of the ARES suite's nondeterminism.

    ``_is_owned_webui_pid`` used to accept ANY process whose command line
    contained ``uvicorn`` and ``fastapi_app.main:app`` — no repo root, no state
    dir, no port. ``ctl.sh stop`` therefore reached across the machine and
    killed the pytest session's own isolated test server, and every later
    HTTP test in the run failed with URLError. That single unscoped match is
    what made a full run report anywhere between 15 and 272 failures.

    This is a source assertion because reproducing it needs a real process
    tree; the behavioural half lives in ``test_ctl_script.py``.
    """
    source = (CONTROLLER / "ctl.sh").read_text(encoding="utf-8")
    unscoped = re.search(
        r'\[\[\s*"\$\{args_slash\}"\s*==\s*\*"uvicorn"\*\s*&&\s*'
        r'"\$\{args_slash\}"\s*==\s*\*"fastapi_app\.main:app"\*\s*\]\]\s*\|\|',
        source,
    )
    assert unscoped is None, (
        "ctl.sh treats any machine-wide uvicorn running this ASGI app as its "
        "own again — it will kill other checkouts and the test server."
    )
    assert "CTL_PORT" in source.split("_is_owned_webui_pid()")[1][:2000], (
        "the uvicorn ownership branch no longer consults CTL_PORT, so it is "
        "unscoped again"
    )


# ── authoritative state must be versioned ──────────────────────────────


def test_the_migration_runner_is_available_to_the_stores():
    """A store cannot version itself with a runner that is not importable."""
    from core.store.migrations import Migration, MigrationStatus, migrate

    assert callable(migrate)
    assert Migration(1, "probe", lambda _c: None).version == 1
    # The three outcomes must stay distinguishable — collapsing them to a
    # boolean is what let a failed migration report success.
    assert len({MigrationStatus.SUCCESS, MigrationStatus.PARTIAL_FAILURE,
                MigrationStatus.FAILED}) == 3


def test_no_new_store_returns_success_shaped_error_strings():
    """The pattern F4 found: per-column ``except`` writing ``"error: ..."``
    into a dict that a 200 response then carried.

    Pinned as a source rule because the shape, not any single call site, is
    the hazard — a reader of the response cannot tell it from success.
    """
    offenders: list[str] = []
    pattern = re.compile(r'=\s*f?"error:\s*\{')
    for path in _python_files(REPO_ROOT / "core"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert offenders == [], (
        "a store is reporting failure as a string inside an otherwise "
        "successful result — return a MigrationReport/status instead:\n"
        + "\n".join(offenders)
    )
