"""Source guard for the ARES/Jaeger ownership boundary."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APPROVED = {
    Path("integrations/providers/jaeger/paths.py"),
}


def test_runtime_sources_do_not_hardcode_jaeger_internal_paths():
    roots = [ROOT / "integrations", ROOT / "services/controller", ROOT / "apps/macos/Sources"]
    forbidden = ("GitHub/JaegerAI", ".jaeger_os")
    findings: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".swift"} or not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if relative in APPROVED or "tests" in relative.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for literal in forbidden:
                if literal in text:
                    findings.append(f"{relative}: {literal}")
    assert findings == [], "Jaeger paths must go through the shared resolver:\n" + "\n".join(findings)


def test_hermes_compat_has_no_persona_or_secret_store_hardcodes():
    source = (ROOT / "services/controller/fastapi_app/routers/hermes_compat.py").read_text(
        encoding="utf-8")
    for forbidden in ("jarvis", ".jaeger_os", "GitHub/JaegerAI", ".hermes"):
        assert forbidden not in source.lower()
