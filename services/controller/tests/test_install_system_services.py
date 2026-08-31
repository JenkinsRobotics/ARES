from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "install-system-services.py"


def _module():
    spec = importlib.util.spec_from_file_location("install_system_services", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_environment_is_allowlisted_and_environment_can_override(tmp_path, monkeypatch):
    for key in _module().PUBLIC_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    config = tmp_path / "config"
    config.mkdir()
    (config / "system-fabric.json").write_text(
        json.dumps({
            "version": 1,
            "environment": {
                "ARES_A2A_PUBLIC_URL": "https://node.example.test/a2a",
                "ARES_WEBUI_PORT": "9000",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARES_WEBUI_PORT", "8788")

    values = _module().load_local_environment(tmp_path)

    assert values == {
        "ARES_A2A_PUBLIC_URL": "https://node.example.test/a2a",
        "ARES_WEBUI_PORT": "8788",
    }


def test_local_environment_rejects_secret_or_unknown_keys(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "system-fabric.json").write_text(
        json.dumps({
            "version": 1,
            "environment": {"OPENCLAW_GATEWAY_TOKEN": "must-not-be-here"},
        }),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="Unsupported System fabric keys"):
        _module().load_local_environment(tmp_path)
