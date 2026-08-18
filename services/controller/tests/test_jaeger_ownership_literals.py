"""Source guard for the ARES/Jaeger ownership boundary."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APPROVED: set[Path] = set()


def test_runtime_sources_do_not_hardcode_jaeger_internal_paths():
    roots = [
        ROOT / "core",
        ROOT / "integrations",
        ROOT / "services/controller",
        ROOT / "apps/macos/Sources",
        ROOT / "apps/web/static",
    ]
    forbidden = (
        "GitHub/JaegerAI",
        ".jaeger_os",
        "/Users/matthewjenkins/",
        "/Users/jonathanjenkins/",
        "hermes",
        "jros",
    )
    findings: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".swift", ".js", ".html", ".css", ".sh", ".strings"} or not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if relative in APPROVED or "tests" in relative.parts or any(part.startswith(".") for part in relative.parts):
                continue
            text = path.read_text(encoding="utf-8").lower()
            for literal in forbidden:
                if literal.lower() in text:
                    findings.append(f"{relative}: {literal}")
    assert findings == [], "Jaeger paths must go through the shared resolver:\n" + "\n".join(findings)


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
