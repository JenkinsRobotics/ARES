"""Native chat-run creation contracts for the FastAPI cutover."""

from __future__ import annotations

import inspect
import threading
from types import SimpleNamespace

from api import chat_runtime


class _Session(SimpleNamespace):
    def save(self, **_kwargs):
        self.saved = getattr(self, "saved", 0) + 1


class _Backend:
    def __init__(self, worker, *, is_gateway=False):
        self.worker = worker
        self.is_gateway = is_gateway

    def get_worker_target(self):
        return self.worker, self.is_gateway, False


def _session():
    return _Session(
        session_id="session-1",
        title="Untitled",
        workspace="/workspace",
        model="model-1",
        model_provider="provider-1",
        profile="default",
        messages=[],
        active_stream_id=None,
        pending_user_message=None,
        pending_attachments=[],
        pending_started_at=None,
        pending_user_source=None,
        truncation_watermark=None,
    )


def _isolate_runtime(monkeypatch, session):
    monkeypatch.setattr(chat_runtime, "STREAMS", {})
    monkeypatch.setattr(chat_runtime, "STREAMS_LOCK", threading.Lock())
    monkeypatch.setattr(chat_runtime, "ACTIVE_RUNS", {})
    monkeypatch.setattr(chat_runtime, "ACTIVE_RUNS_LOCK", threading.Lock())
    monkeypatch.setattr(chat_runtime, "PENDING_GOAL_CONTINUATION", set())
    monkeypatch.setattr(chat_runtime, "PENDING_BG_TASK_COMPLETIONS", set())
    monkeypatch.setattr(chat_runtime, "STREAM_GOAL_RELATED", {})
    monkeypatch.setattr(chat_runtime, "get_session", lambda *_args, **_kwargs: session)
    monkeypatch.setattr(chat_runtime, "get_config", lambda: {"model": {"default": "model-1"}})
    monkeypatch.setattr(chat_runtime, "get_effective_default_model", lambda _cfg: "model-1")
    monkeypatch.setattr(chat_runtime, "get_last_workspace", lambda: "/workspace")
    monkeypatch.setattr(chat_runtime, "resolve_trusted_workspace", lambda value: value)
    monkeypatch.setattr(chat_runtime, "set_last_workspace", lambda _value: None)
    monkeypatch.setattr(chat_runtime, "get_webui_session_save_mode", lambda: "deferred")
    monkeypatch.setattr(chat_runtime, "_get_session_agent_lock", lambda _sid: threading.Lock())
    monkeypatch.setattr(chat_runtime, "create_stream_channel", lambda: SimpleNamespace())
    monkeypatch.setattr(chat_runtime, "register_stream_owner", lambda *_args: None)
    monkeypatch.setattr(chat_runtime, "unregister_stream_owner", lambda *_args: None)
    monkeypatch.setattr(chat_runtime, "publish_session_list_changed", lambda *_args, **_kwargs: None)
    # Directives are read from ARES_HOME and prepended to every execution
    # prompt, so without this these tests assert against whatever rules the
    # developer happens to have enabled on their own machine.
    monkeypatch.setattr("api.ares_directives.load_active_directives", lambda: [])


def test_native_chat_runtime_has_no_legacy_route_dependency():
    assert "api.routes" not in inspect.getsource(chat_runtime)


def test_backend_model_resolution_replaces_an_incompatible_retained_model():
    backend = SimpleNamespace(
        name="codex_local",
        inventory=lambda: {
            "models": [
                {"id": "gpt-5.6-sol", "provider": "openai", "in_use": True},
                {"id": "gpt-5.4", "provider": "openai", "in_use": False},
            ]
        },
    )

    assert chat_runtime.resolve_backend_execution_model(
        backend,
        "qwen3.5:397b",
        "ollama-cloud",
    ) == ("gpt-5.6-sol", "openai")


def test_explicit_framework_display_preserves_its_executed_model():
    from api.model_resolution import (
        _resolve_effective_session_model_for_display,
        _resolve_effective_session_model_provider_for_display,
    )

    session = SimpleNamespace(
        ares_backend="codex_local",
        model="gpt-5.6-sol",
        model_provider=None,
    )

    assert _resolve_effective_session_model_for_display(session) == "gpt-5.6-sol"
    assert _resolve_effective_session_model_provider_for_display(session) is None


def test_native_chat_runtime_registers_stream_and_starts_worker(monkeypatch):
    session = _session()
    _isolate_runtime(monkeypatch, session)
    worker_calls = []
    thread_calls = []

    def worker(*args, **kwargs):
        worker_calls.append((args, kwargs))

    class ImmediateThread:
        def __init__(self, *, target, args, kwargs, **_rest):
            thread_calls.append((target, args, kwargs))

        def start(self):
            target, args, kwargs = thread_calls[-1]
            target(*args, **kwargs)

    monkeypatch.setattr(chat_runtime.threading, "Thread", ImmediateThread)

    result = chat_runtime.start_session_turn(
        session.session_id,
        "  Hello  ",
        source="webui",
        backend=_Backend(worker),
    )

    assert result["session_id"] == session.session_id
    assert result["stream_id"] in chat_runtime.STREAMS
    assert session.pending_user_message == "Hello"
    assert session.active_stream_id == result["stream_id"]
    assert session.saved == 1
    assert worker_calls[0][0][0] == session.session_id
    assert worker_calls[0][0][1].endswith("\n\nHello")
    assert worker_calls[0][1]["model_provider"] == "provider-1"


def test_adapter_context_identifies_selected_framework_and_model(monkeypatch):
    session = _session()
    _isolate_runtime(monkeypatch, session)
    worker_calls = []

    from api.providers.agentic_backend import run_agentic_backend_streaming

    class CapturingThread:
        def __init__(self, *, target, args, kwargs, **_rest):
            worker_calls.append((target, args, kwargs))

        def start(self):
            return None

    monkeypatch.setattr(chat_runtime.threading, "Thread", CapturingThread)
    backend = _Backend(run_agentic_backend_streaming)
    backend.name = "codex_local"

    chat_runtime.start_session_turn(
        session.session_id,
        "Which model?",
        source="webui",
        backend=backend,
    )

    prompt = worker_calls[0][1][1]
    assert "Selected framework: OpenAI Codex (codex_local)." in prompt
    assert "Selected model: model-1." in prompt
    assert worker_calls[0][2]["user_message"] == "Which model?"


def test_gateway_worker_receives_clean_turn_without_serialized_transcript(monkeypatch):
    session = _session()
    session.messages = [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
    ]
    _isolate_runtime(monkeypatch, session)
    worker_calls = []

    def worker(*args, **kwargs):
        worker_calls.append((args, kwargs))

    class ImmediateThread:
        def __init__(self, *, target, args, kwargs, **_rest):
            self.target, self.args, self.kwargs = target, args, kwargs

        def start(self):
            self.target(*self.args, **self.kwargs)

    monkeypatch.setattr(chat_runtime.threading, "Thread", ImmediateThread)

    chat_runtime.start_session_turn(
        session.session_id,
        "New question",
        source="webui",
        backend=_Backend(worker, is_gateway=True),
    )

    assert worker_calls[0][0][1] == "New question"
    assert "Previous conversation" not in worker_calls[0][0][1]


def test_native_chat_runtime_rejects_duplicate_active_stream(monkeypatch):
    session = _session()
    session.active_stream_id = "existing-run"
    _isolate_runtime(monkeypatch, session)
    chat_runtime.STREAMS["existing-run"] = SimpleNamespace()

    result = chat_runtime.start_session_turn(
        session.session_id,
        "Hello",
        source="webui",
        backend=_Backend(lambda *_args, **_kwargs: None),
    )

    assert result["_status"] == 409
    assert result["active_stream_id"] == "existing-run"
    # The rejection has to be actionable: a bare 409 reads as a lost message,
    # so the client is told this is a wait-and-resend, not a refusal.
    assert result["retry"] is True
    assert result["reason"]
    assert result["fix"]
