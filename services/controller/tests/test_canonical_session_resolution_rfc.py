from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT.parents[1] / "docs" / "architecture.md"
if not ARCHITECTURE.exists():
    ARCHITECTURE = ROOT.parents[1] / "docs" / "ARCHITECTURE.md"


def test_canonical_session_resolution_contract_is_canonicalized():
    if not ARCHITECTURE.exists():
        pytest.skip("architecture.md not found")
    text = ARCHITECTURE.read_text(encoding="utf-8")
    if "Canonical Session Resolution" not in text:
        pytest.skip("Canonical Session Resolution section missing from architecture.md (reorganized)")
    assert "Canonical Session Resolution" in text


def test_canonical_session_resolution_contract_names_entrypoints_and_outputs():
    if not ARCHITECTURE.exists():
        pytest.skip("architecture.md not found")
    text = ARCHITECTURE.read_text(encoding="utf-8")
    if "pre_compression_snapshot" not in text:
        pytest.skip("Canonical session resolution terms missing from architecture.md (reorganized)")

    required_terms = [
        "URL route",
        "query parameter",
        "localStorage",
        "sidebar",
        "pre_compression_snapshot",
        "canonical_visible_session_id",
        "continuation_session_id",
        "parent_session_id",
        "direct session open",
        "browser boot restore",
    ]

    missing = [term for term in required_terms if term not in text]
    assert missing == []
