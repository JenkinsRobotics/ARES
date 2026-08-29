from __future__ import annotations

import json
from pathlib import Path

import host_capability_mcp_server as host


def configure(tmp_path: Path, monkeypatch, *, identity: str = "hermes") -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    grants = tmp_path / "grants.json"
    grants.write_text(json.dumps({
        "version": 1,
        "identities": {
            identity: {
                "roots": [str(workspace)],
                "capabilities": [
                    "capabilities.inspect", "workspace.list", "workspace.read",
                    "workspace.write", "workspace.mkdir", "git.status", "git.diff",
                    "service.status",
                ],
            },
        },
    }))
    monkeypatch.setattr(host, "IDENTITY", identity)
    monkeypatch.setattr(host, "GRANTS_PATH", grants)
    monkeypatch.setattr(host, "AUDIT_PATH", tmp_path / "audit" / "events.jsonl")
    return workspace


def test_workspace_write_is_atomic_and_requires_overwrite_precondition(tmp_path, monkeypatch):
    workspace = configure(tmp_path, monkeypatch)
    created = host.workspace_write("/workspace/result.txt", "one")
    assert (workspace / "result.txt").read_text() == "one"
    assert created["sha256"]

    try:
        host.workspace_write("/workspace/result.txt", "two")
    except RuntimeError as exc:
        assert "precondition failed" in str(exc)
    else:
        raise AssertionError("existing file was overwritten without its current hash")

    updated = host.workspace_write("/workspace/result.txt", "two", created["sha256"])
    assert updated["sha256"] != created["sha256"]
    assert (workspace / "result.txt").read_text() == "two"


def test_workspace_rejects_traversal_and_symlink_escape(tmp_path, monkeypatch):
    workspace = configure(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)

    for value in ["/workspace/../outside", "/workspace/escape/secret.txt"]:
        try:
            host._resolve(value, must_exist=False, capability="workspace.read")
        except PermissionError as exc:
            assert "outside" in str(exc)
        else:
            raise AssertionError(f"unsafe path was accepted: {value}")
    audit = host.AUDIT_PATH.read_text()
    assert audit.count('"outcome": "denied"') == 2
    assert "PermissionError" in audit


def test_capability_registry_and_audit_do_not_contain_file_content(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    host.workspace_write("note.txt", "do-not-log-this-content")
    result = host.capabilities_inspect()
    assert result["identity"] == "hermes"
    assert result["limits"]["arbitrary_shell"] is False
    audit = host.AUDIT_PATH.read_text()
    assert "workspace.write" in audit
    assert "do-not-log-this-content" not in audit


def test_ungranted_capability_fails_closed(tmp_path, monkeypatch):
    workspace = configure(tmp_path, monkeypatch)
    host.GRANTS_PATH.write_text(json.dumps({
        "version": 1,
        "identities": {"hermes": {"roots": [str(workspace)], "capabilities": []}},
    }))
    try:
        host.workspace_list()
    except PermissionError as exc:
        assert "not granted" in str(exc)
    else:
        raise AssertionError("ungranted capability was allowed")
