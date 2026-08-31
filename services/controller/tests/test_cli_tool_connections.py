"""Regression checks for launchd-visible, non-durable CLI connections."""

from types import SimpleNamespace

from api.backends.cli_backends import (
    ClaudeLocalBackend,
    CodexLocalBackend,
    GeminiLocalBackend,
    GrokLocalBackend,
    PiLocalBackend,
)

from fastapi_app.adapters import AdapterRegistry


def test_default_registry_includes_every_installed_cli_connection():
    registry = AdapterRegistry()
    for connection_id in (
        "claude_local",
        "codex_local",
        "gemini_local",
        "grok_local",
        "pi_local",
    ):
        assert registry.execution_adapter(connection_id).adapter_id == connection_id


def test_cli_resolution_checks_bounded_host_tool_directories(monkeypatch, tmp_path):
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o700)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "api.backends.cli_backends_legacy._host_tool_dirs",
        lambda: (str(tmp_path),),
    )
    assert CodexLocalBackend()._cli_path() == str(executable)


def test_cli_probe_uses_bounded_runtime_path(monkeypatch):
    backend = CodexLocalBackend()
    monkeypatch.setattr(backend, "_cli_path", lambda: "/opt/homebrew/bin/codex")
    observed = {}

    def run(_args, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="codex 1\n")

    monkeypatch.setattr("subprocess.run", run)
    assert backend.is_available()
    assert "/opt/homebrew/bin" in observed["env"]["PATH"].split(":")


def test_headless_cli_connections_default_to_read_only_modes():
    assert "plan" in (ClaudeLocalBackend.extra_args or [])
    assert "read-only" in (CodexLocalBackend.extra_args or [])
    assert "plan" in (GeminiLocalBackend.extra_args or [])
    assert GrokLocalBackend.prompt_flag == "-p"
    assert "plan" in (GrokLocalBackend.extra_args or [])
    args = PiLocalBackend()._build_args("/usr/local/bin/pi", "hello", "model")
    assert "--no-tools" in args
    assert "--thinking" in args and "off" in args
    assert "--provider" in args and "ollama" in args
