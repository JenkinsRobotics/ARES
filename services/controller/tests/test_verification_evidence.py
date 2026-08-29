from __future__ import annotations

import json

from api import verification_evidence as evidence


def test_evidence_marks_commit_mismatch_stale(tmp_path, monkeypatch):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({
        "schema": "ares-jaeger-five-promises/v1",
        "finished_at": "2026-01-01T00:00:00Z",
        "commits": {"ares": "old-a", "jaeger": "old-j"},
        "promises": {"memory": {"result": "pass", "boundary": "live", "expected": "x", "actual": "x"}},
    }))
    monkeypatch.setattr(evidence, "_git_head", lambda path: "new-a" if path.name == "ARES" else "new-j")
    result = evidence.verification_evidence(path)
    assert result["available"] is True
    assert result["stale"] is True
    assert result["stale_components"] == ["ares", "jaeger"]
    assert result["promises"][0]["boundary"] == "live"


def test_evidence_fails_closed_on_bad_schema(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text('{"schema":"unknown"}')
    result = evidence.verification_evidence(path)
    assert result == {
        "available": False,
        "reason": "Evidence schema is unsupported.",
        "source": str(path),
    }


def test_evidence_does_not_claim_missing_file_passed(tmp_path):
    result = evidence.verification_evidence(tmp_path / "missing.json")
    assert result["available"] is False
    assert "No runtime evidence" in result["reason"]
