"""Regression coverage for two real bugs found live-probing OllamaLocalBackend
(integrations/workers/cli_backends.py) against an actual local Ollama install:

1. run_turn() defaulted to a hardcoded "llama3.2" when no model was
   specified, regardless of what was actually installed. Confirmed live:
   this machine has gemini-3-flash-preview:latest / qwen3.6:35b-mlx /
   gemma4:31b-mlx installed — none of them "llama3.2" — so every call with
   no explicit model 404'd.

2. The non-streaming branch never called r.raise_for_status(), so that
   404 (or any other Ollama HTTP error) fell through to
   ``data.get("message", {}).get("content", "")`` — which is "" for an
   error body with no "message" key — silently returning empty text with
   error=None. CLAUDE.md: no silent default worker, report what dropped.

Both are mocked here (no real Ollama instance required in CI) via
monkeypatching model_discovery.list_ollama_local_models and requests.post.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from integrations.workers.cli_backends import OllamaLocalBackend


@pytest.fixture(autouse=True)
def _ollama_reachable(monkeypatch):
    """is_available() probes /api/tags directly; stub it available so
    run_turn() doesn't short-circuit before reaching the code under test."""
    monkeypatch.setattr(OllamaLocalBackend, "is_available", lambda self: True)


def test_resolve_default_model_uses_first_real_installed_model(monkeypatch):
    monkeypatch.setattr(
        "integrations.workers.model_discovery.list_ollama_local_models",
        lambda: [{"id": "qwen3.6:35b-mlx"}, {"id": "gemma4:31b-mlx"}],
    )
    backend = OllamaLocalBackend()
    assert backend._resolve_default_model() == "qwen3.6:35b-mlx"


def test_resolve_default_model_is_none_when_nothing_installed(monkeypatch):
    monkeypatch.setattr(
        "integrations.workers.model_discovery.list_ollama_local_models",
        lambda: [],
    )
    backend = OllamaLocalBackend()
    assert backend._resolve_default_model() is None


def test_run_turn_with_no_models_installed_is_an_honest_error(monkeypatch):
    """Never fabricate a model name when none are installed — an honest,
    actionable error beats a guaranteed-to-404 hardcoded guess."""
    monkeypatch.setattr(
        "integrations.workers.model_discovery.list_ollama_local_models",
        lambda: [],
    )
    backend = OllamaLocalBackend()
    result = backend.run_turn("hello", session_id="s1")
    assert result["text"] == ""
    assert result["error"] and "no ollama models" in result["error"].lower()


def test_run_turn_surfaces_http_error_instead_of_silent_empty_text(monkeypatch):
    """The actual bug: a 404 (retired/missing model) must become a real
    error, not '' with error=None."""
    monkeypatch.setattr(
        "integrations.workers.model_discovery.list_ollama_local_models",
        lambda: [{"id": "some-model"}],
    )

    fake_response = MagicMock()
    fake_response.raise_for_status.side_effect = Exception(
        "410 Client Error: Gone for url: http://127.0.0.1:11434/api/chat"
    )
    monkeypatch.setattr(
        "requests.post", lambda *a, **k: fake_response
    )

    backend = OllamaLocalBackend()
    result = backend.run_turn("hello", session_id="s1")
    assert result["text"] == ""
    assert "410" in result["error"]


def test_run_turn_returns_real_reply_on_success(monkeypatch):
    monkeypatch.setattr(
        "integrations.workers.model_discovery.list_ollama_local_models",
        lambda: [{"id": "some-model"}],
    )

    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"message": {"content": "pong"}}
    monkeypatch.setattr("requests.post", lambda *a, **k: fake_response)

    backend = OllamaLocalBackend()
    result = backend.run_turn("ping", session_id="s1")
    assert result == {"text": "pong", "error": None, "tool_activity": []}
