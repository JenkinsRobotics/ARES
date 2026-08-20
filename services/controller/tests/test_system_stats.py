"""Tests for system & AI model telemetry (api/system_stats.py)."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from api.system_stats import get_system_stats, _query_ollama_ps, _query_jaeger_status


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
