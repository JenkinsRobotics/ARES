"""Tests for system & AI model telemetry (api/system_stats.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from api.system_stats import _query_jaeger_status, _query_ollama_ps, get_system_stats


def test_system_stats_returns_valid_structure():
    stats = get_system_stats(profile_name="Jarvis", force_refresh=True)

    assert stats["ok"] is True
    assert stats["profile"] == "Jarvis"
    assert "host" in stats
    assert "cpu_percent" in stats["host"]
    assert "memory" in stats["host"]
    assert "percent" in stats["host"]["memory"]
    assert "used_gb" in stats["host"]["memory"]
    assert "total_gb" in stats["host"]["memory"]
    assert "ai_runtimes" in stats
    assert "ollama" in stats["ai_runtimes"]
    assert "jaeger" in stats["ai_runtimes"]
    assert "swap" in stats["host"]
    assert "memory_breakdown" in stats["host"]
    assert stats["host"]["metrics_source"]


def test_system_stats_process_inventory_is_opt_in_and_bounded(monkeypatch):
    monkeypatch.setattr(
        "api.system_stats._top_processes",
        lambda limit: [{"pid": value, "name": "safe", "memory_bytes": value}
                       for value in range(limit)],
    )
    ordinary = get_system_stats(force_refresh=True)
    detailed = get_system_stats(include_processes=True, process_limit=3)

    assert "top_processes" not in ordinary["host"]
    assert len(detailed["host"]["top_processes"]) == 3


def test_ollama_ps_parser_with_loaded_models():
    mock_response = {
        "models": [
            {
                "name": "qwen2.5-coder:7b",
                "model": "qwen2.5-coder:7b",
                "size": 4900000000,
                "size_vram": 4900000000,
                "expires_at": "2026-08-18T00:00:00Z",
                "details": {"parameter_size": "7B", "quantization_level": "Q4_K_M"},
            }
        ]
    }

    mock_resp_obj = MagicMock()
    mock_resp_obj.status = 200
    mock_resp_obj.read.return_value = json.dumps(mock_response).encode("utf-8")
    mock_resp_obj.__enter__.return_value = mock_resp_obj

    with patch("urllib.request.urlopen", return_value=mock_resp_obj):
        result = _query_ollama_ps()
        assert result["available"] is True
        assert result["status"] == "loaded"
        assert result["loaded_models_count"] == 1
        assert result["models"][0]["name"] == "qwen2.5-coder:7b"
        assert "4.56 GB" in result["models"][0]["size_vram_formatted"] or "GB" in result["models"][0]["size_vram_formatted"]


def test_ollama_ps_parser_when_offline():
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        result = _query_ollama_ps()
        assert result["available"] is False
        assert result["status"] == "offline"
        assert result["loaded_models_count"] == 0
        assert result["models"] == []


def test_jaeger_status_query():
    stat = _query_jaeger_status()
    assert "available" in stat
    assert "status" in stat
    assert stat["runtime_owner"] == "jaeger"
