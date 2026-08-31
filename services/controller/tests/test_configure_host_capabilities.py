from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "configure-host-capabilities.py"


def _module():
    spec = importlib.util.spec_from_file_location("configure_host_capabilities", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reconciles_to_workspace_only_and_preserves_previous(tmp_path, monkeypatch):
    state = tmp_path / "state"
    workspace = tmp_path / "workspace"
    grants = state / "capabilities" / "grants.json"
    grants.parent.mkdir(parents=True)
    grants.write_text(
        json.dumps({
            "version": 1,
            "identities": {
                "hermes": {"roots": ["/private/repository"], "capabilities": ["workspace.read"]},
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARES_HOME", str(state))
    monkeypatch.setenv("ARES_SHARED_WORKSPACE", str(workspace))

    assert _module().main() == 0

    document = json.loads(grants.read_text(encoding="utf-8"))
    assert document["identities"]["hermes"]["roots"] == [str(workspace)]
    assert document["identities"]["jaeger"]["roots"] == [str(workspace)]
    assert "workspace.write" in document["identities"]["hermes"]["capabilities"]
    assert "capability.request" not in document["identities"]["hermes"]["capabilities"]
    previous = json.loads(grants.with_suffix(".json.previous").read_text(encoding="utf-8"))
    assert previous["identities"]["hermes"]["roots"] == ["/private/repository"]


def test_operator_policy_adds_only_explicit_absolute_roots(tmp_path, monkeypatch):
    state = tmp_path / "state"
    workspace = tmp_path / "workspace"
    repository = tmp_path / "repository"
    repository.mkdir()
    config = state / "config"
    config.mkdir(parents=True)
    (config / "host-capabilities.json").write_text(
        json.dumps({
            "version": 1,
            "identities": {
                "admin": {"additional_roots": [str(repository)]},
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARES_HOME", str(state))
    monkeypatch.setenv("ARES_SHARED_WORKSPACE", str(workspace))

    assert _module().main() == 0

    document = json.loads(
        (state / "capabilities" / "grants.json").read_text(encoding="utf-8")
    )
    assert document["identities"]["hermes"]["roots"] == [str(workspace)]
    assert set(document["identities"]["admin"]["roots"]) == {
        str(workspace),
        str(repository),
    }
