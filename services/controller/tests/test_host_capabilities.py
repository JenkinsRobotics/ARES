from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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
    assert not hasattr(host, "terminal_execute")
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


def test_jxa_keeps_untrusted_values_out_of_the_program(monkeypatch):
    observed = {}

    def run(args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(host.subprocess, "run", run)
    attack = '\"; Application(\"System Events\").doShellScript(\"touch /tmp/pwned\"); //'
    result = host._run_jxa("function run(argv) { return argv[0]; }", {"title": attack})
    assert result["exit_code"] == 0
    assert attack not in observed["args"][4]
    assert json.loads(observed["args"][-1])["title"] == attack
    assert observed["kwargs"]["stdin"] is host.subprocess.DEVNULL


def test_calendar_write_returns_approval_before_jxa(tmp_path, monkeypatch):
    workspace = configure(tmp_path, monkeypatch)
    data = json.loads(host.GRANTS_PATH.read_text())
    data["identities"]["hermes"]["capabilities"].append("calendar.create")
    host.GRANTS_PATH.write_text(json.dumps(data))
    called = []
    monkeypatch.setattr(
        host, "_authorize_effect",
        lambda *_args, **_kwargs: {"status": "approval_required", "approval_id": "approval-1"},
    )
    monkeypatch.setattr(host, "_run_jxa", lambda *_args, **_kwargs: called.append(True))
    result = host.calendar_create(
        "Review", "2026-08-31T10:00:00", "2026-08-31T11:00:00",
    )
    assert result == {"status": "approval_required", "approval_id": "approval-1"}
    assert called == []
    assert workspace.is_dir()


def test_effect_lease_binds_to_exact_typed_payload(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    data = json.loads(host.GRANTS_PATH.read_text())
    data["identities"]["hermes"]["capabilities"].append("shortcuts.run")
    host.GRANTS_PATH.write_text(json.dumps(data))
    calls = []
    monkeypatch.setattr(host, "_system_request", lambda path, payload: calls.append((path, payload)) or {"authorized": True})
    values = {"name": "Safe Shortcut", "input": "hello"}
    assert host._authorize_effect(
        "shortcuts.run", values, "approval-1", reason="run", benefit="benefit",
        risks=["risk"], scope="one", reversible="unknown",
        safer_alternative="deny", data_destination="shortcut",
    ) is None
    path, payload = calls[0]
    assert path == "/api/effects/approval-1/consume"
    expected, _ = host._effect_payload("shortcuts.run", values)
    assert payload["payload_sha256"] == expected
    assert "hello" not in json.dumps(payload)


def test_camera_capabilities_gating_and_audit(tmp_path, monkeypatch):
    workspace = configure(tmp_path, monkeypatch)
    # 1. Un-granted camera.status should fail closed
    try:
        host.camera_status()
    except PermissionError as exc:
        assert "not granted" in str(exc)
    else:
        raise AssertionError("ungranted camera.status was allowed")

    # 2. Grant camera.status and camera.ptz
    host.GRANTS_PATH.write_text(json.dumps({
        "version": 1,
        "identities": {
            "hermes": {
                "roots": [str(workspace)],
                "capabilities": ["camera.status", "camera.ptz"],
            },
        },
    }))

    # Verify status runs and audits
    info = host.camera_status()
    assert isinstance(info, dict)
    assert info["device"] == "Insta360 Link 2"
    audit = host.AUDIT_PATH.read_text()
    assert "camera.status" in audit
