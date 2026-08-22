"""Unit tests for the ARES Local Model Evaluation and Orchestrator Benchmark Suite."""

from __future__ import annotations

import json
import pytest
from starlette.testclient import TestClient

from core.evaluation.eval_suite import (
    TEST_CASES,
    evaluate_test_case,
    evaluate_model,
    run_orchestrator_evaluation_suite,
    generate_eval_markdown_report,
    save_eval_results,
    load_latest_eval_results,
)
from fastapi_app.main import app


def mock_good_caller(model, prompt, base_url="http://localhost:11434", timeout=60.0, history=None):
    """Simulate a capable model returning accurate, well-formed answers."""
    p_lower = prompt.lower()
    if "weather" in p_lower:
        return True, "get_weather", 0.4, 0.1, {"eval_count": 5, "tokens_per_sec": 30.0, "ttft_sec": 0.1}
    if "skills/" in p_lower:
        return True, "There are 5 skills in the directory starting with test_skill.py", 0.5, 0.1, {"eval_count": 15, "tokens_per_sec": 30.0, "ttft_sec": 0.1}
    if "stored" in p_lower:
        return True, "stored", 0.3, 0.1, {"eval_count": 2, "tokens_per_sec": 30.0, "ttft_sec": 0.1}
    if "favorite color" in p_lower:
        return True, "Your favorite color is blue.", 0.3, 0.1, {"eval_count": 6, "tokens_per_sec": 30.0, "ttft_sec": 0.1}
    if "2+2" in p_lower:
        return True, "2+2 equals 4.", 0.2, 0.1, {"eval_count": 5, "tokens_per_sec": 30.0, "ttft_sec": 0.1}
    if "email sam" in p_lower:
        return True, "My first step is to lookup Sam's email address in contacts.", 0.5, 0.1, {"eval_count": 14, "tokens_per_sec": 30.0, "ttft_sec": 0.1}
    if "distinct execution steps" in p_lower:
        return True, "That requires 4 distinct steps (3 processing + 1 merge).", 0.4, 0.1, {"eval_count": 12, "tokens_per_sec": 30.0, "ttft_sec": 0.1}
    if "falcon77" in p_lower:
        return True, "noted", 0.2, 0.1, {"eval_count": 2, "tokens_per_sec": 30.0, "ttft_sec": 0.1}
    if "secret access code" in p_lower:
        return True, "The secret access code is Falcon77.", 0.3, 0.1, {"eval_count": 7, "tokens_per_sec": 30.0, "ttft_sec": 0.1}
    if "file not found" in p_lower:
        return True, "I would search the directory tree for alternate matching filenames.", 0.5, 0.1, {"eval_count": 12, "tokens_per_sec": 30.0, "ttft_sec": 0.1}
    return True, "ready", 0.1, 0.1, {"eval_count": 2, "tokens_per_sec": 30.0, "ttft_sec": 0.1}


def mock_flawed_caller(model, prompt, base_url="http://localhost:11434", timeout=60.0, history=None):
    """Simulate a flawed model returning markdown violations and wrong answers."""
    p_lower = prompt.lower()
    if "2+2" in p_lower:
        # Violates both no_markdown and one_sentence
        return True, "**Answer:**\n\nThe sum of 2 and 2 is 4. This is basic arithmetic.", 0.8, 0.2, {"eval_count": 20, "tokens_per_sec": 25.0, "ttft_sec": 0.2}
    return True, "I am unsure what to do here.", 0.6, 0.2, {"eval_count": 8, "tokens_per_sec": 20.0, "ttft_sec": 0.2}


def test_evaluate_test_case_accurate():
    """Test evaluating a test case with a compliant model."""
    t1 = TEST_CASES[0]
    res = evaluate_test_case("test_model", t1, caller_fn=mock_good_caller)
    assert res["status"] == "passed"
    assert res["score"] == 5
    assert "correct" in res["notes"]


def test_evaluate_test_case_constraints():
    """Test markdown and multi-sentence penalties."""
    t4 = [t for t in TEST_CASES if t["id"] == "T4_output_constraint"][0]
    res = evaluate_test_case("flawed_model", t4, caller_fn=mock_flawed_caller)
    # 10 max points -> 10 correct text - 2 markdown - 2 multi_sentence = 6
    assert res["score"] < 10
    assert "[markdown violation]" in res["notes"]
    assert "[multi-sentence]" in res["notes"]


def test_evaluate_model_full_suite():
    """Test full evaluation pipeline on a model."""
    result = evaluate_model("good_model:35b", caller_fn=mock_good_caller)
    assert result["model"] == "good_model:35b"
    assert result["total_score"] >= 80
    assert result["verdict"] == "PASS"
    assert len(result["results"]) == len(TEST_CASES)


def test_markdown_report_formatting():
    """Test generating a markdown scorecard table."""
    summary = {
        "timestamp": "2026-08-22T12:00:00Z",
        "models_evaluated": 1,
        "recommended_orchestrator": "qwen3.6:35b-mlx",
        "results": [
            {
                "model": "qwen3.6:35b-mlx",
                "total_score": 95,
                "max_score": 100,
                "percentage": 95.0,
                "verdict": "PASS",
                "avg_latency_sec": 1.2,
                "avg_ttft_sec": 0.4,
                "results": [
                    {
                        "test_id": "T1_simple_lookup",
                        "category": "tool_accuracy",
                        "score": 5,
                        "max_points": 5,
                        "status": "passed",
                        "latency_sec": 0.4,
                        "output_preview": "get_weather",
                    }
                ],
            }
        ],
    }
    md = generate_eval_markdown_report(summary)
    assert "Local Model Orchestrator Benchmark" in md
    assert "qwen3.6:35b-mlx" in md
    assert "95.0%" in md
    assert "PASS" in md


def test_fastapi_model_eval_endpoints(monkeypatch):
    """Test GET and POST eval routes in FastAPI."""
    import core.evaluation.eval_suite as es
    monkeypatch.setattr(es, "call_ollama", mock_good_caller)

    client = TestClient(app)
    
    # 1. Run eval
    run_resp = client.post(
        "/api/models/eval/run",
        json={"models": ["test_orchestrator:35b"]},
        headers={"Authorization": "Bearer local-test", "X-Profile": "default"},
    )
    assert run_resp.status_code == 200
    data = run_resp.json()
    assert data["status"] == "success"
    assert data["summary"]["recommended_orchestrator"] == "test_orchestrator:35b"

    # 2. Get results
    get_resp = client.get(
        "/api/models/eval/results",
        headers={"Authorization": "Bearer local-test", "X-Profile": "default"},
    )
    assert get_resp.status_code == 200
    res_data = get_resp.json()
    assert res_data["status"] == "success"
    assert res_data["summary"]["recommended_orchestrator"] == "test_orchestrator:35b"
