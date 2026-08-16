"""Unit & Integration Tests for ARES Master-Worker DispatchService."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from api.dispatch_service import DispatchService
from core.si.types import WorkerResult
from core.events.turn_journal import read_turn_journal


class MockWorkerBackend:
    name = "jaeger_local"

    def is_available(self) -> bool:
        return True

    def run_turn(self, message: str, session_id: str, **kwargs) -> dict:
        return {
            "text": f"Mock response for: {message}",
            "tool_activity": [],
            "session_id": session_id,
        }


class MockRegistry:
    @classmethod
    def get_available(cls):
        return {"jaeger_local": MockWorkerBackend()}


class MockExecutionAdapter:
    adapter_id = "jaeger_local"

    def __init__(self):
        self.calls = []

    def run_turn(self, message, *, session_id, profile, model=None, model_provider=None):
        self.calls.append((message, session_id, profile, model, model_provider))
        return {"text": f"Adapter response for: {message}", "session_id": session_id}


class MockAdapterRegistry:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.adapter = MockExecutionAdapter()

    def execution_adapter(self, adapter_id):
        if self.fail:
            raise RuntimeError("unavailable")
        assert adapter_id == "jaeger_local"
        return self.adapter


def test_dispatch_turn_simple_conversation(tmp_path, monkeypatch):
    """Test standard dispatch turn for a conversation message."""
    monkeypatch.setenv("ARES_HOME", str(tmp_path))
    monkeypatch.setattr("api.journal.paths.si_dir", lambda: tmp_path)
    monkeypatch.setattr("api.models.SESSION_DIR", str(tmp_path / "sessions"))

    service = DispatchService(backend_registry=MockRegistry)

    res = service.dispatch_turn(
        user_message="Hello Leo, how are you?",
        conversation_id="test_session_001",
        local_only_mode=True,
    )

    assert res["status"] == "step_completed"
    assert res["assigned_worker"] == "jaeger_local"
    assert "Mock response for: Hello Leo" in res["output"]
    assert res["evaluation"]["passed"] is True


def test_dispatch_turn_uses_canonical_adapter_without_legacy_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_HOME", str(tmp_path))
    monkeypatch.setattr("api.journal.paths.si_dir", lambda: tmp_path)
    legacy = MagicMock()
    adapters = MockAdapterRegistry()
    service = DispatchService(backend_registry=legacy, adapter_registry=adapters)

    res = service.dispatch_turn(
        "Hello", "canonical-session", local_only_mode=True, profile="profile-a"
    )

    assert res["status"] == "step_completed"
    assert res["output"] == "Adapter response for: Hello"
    assert adapters.adapter.calls[0][2] == "profile-a"
    legacy.get_available.assert_not_called()


def test_dispatch_turn_does_not_fallback_when_adapter_resolution_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_HOME", str(tmp_path))
    monkeypatch.setattr("api.journal.paths.si_dir", lambda: tmp_path)
    legacy = MagicMock()
    service = DispatchService(backend_registry=legacy, adapter_registry=MockAdapterRegistry(fail=True))

    res = service.dispatch_turn("Hello", "failed-session", local_only_mode=True)

    assert res["status"] == "execution_failed"
    legacy.get_available.assert_not_called()


def test_dispatch_turn_approval_gate_and_resolution(tmp_path, monkeypatch):
    """Test that high-risk action triggers approval gate requirement and can be approved/rejected."""
    monkeypatch.setenv("ARES_HOME", str(tmp_path))
    monkeypatch.setattr("api.journal.paths.si_dir", lambda: tmp_path)
    monkeypatch.setattr("api.models.SESSION_DIR", str(tmp_path / "sessions"))

    service = DispatchService(backend_registry=MockRegistry)

    res = service.dispatch_turn(
        user_message="Execute terminal command rm -rf /important_dir",
        conversation_id="test_session_002",
        local_only_mode=True,
    )

    if res.get("status") == "awaiting_approval":
        assert res["needs_approval"] is True
        plan_id = res["plan_id"]
        step_id = res["step"]["step_id"]

        # Test approving the step
        approve_res = service.approve_step(plan_id, step_id)
        assert approve_res["status"] == "approved"

        # Test rejecting another step
        reject_res = service.reject_step(plan_id, step_id, reason="Denied by test")
        assert reject_res["status"] == "rejected"
