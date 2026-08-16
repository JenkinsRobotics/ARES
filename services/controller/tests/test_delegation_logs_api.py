"""Unit tests for /api/delegation/logs endpoint — path traversal protection."""

import pytest
from pathlib import Path


def test_delegation_logs_path_traversal_blocks_escaping(tmp_path, monkeypatch):
    """
    Security: /api/delegation/log must refuse any path that escapes
    ~/.hermes/cache/delegation/live/ — even if the caller crafts a
    malicious absolute path or uses ../.. sequences.
    """
    # Create a fake home directory with a delegation live dir
    fake_home = tmp_path / "fake_home"
    fake_hermes = fake_home / ".hermes" / "cache" / "delegation" / "live"
    fake_hermes.mkdir(parents=True)
    
    # Create a secret file OUTSIDE the live dir
    secret_file = fake_home / "secret.txt"
    secret_file.write_text("DO NOT EXPOSE")
    
    # Create a legit log file INSIDE the live dir
    legit_log = fake_hermes / "task-0.log"
    legit_log.write_text("Agent running...")
    
    # Monkeypatch Path.home to return our fake home
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    
    # Import the endpoint function directly
    from fastapi_app.routers.file_delivery import read_delegation_log
    from fastapi_app.errors import CoreApiError
    
    # Mock identity (not used in the function, but required by signature)
    class FakeIdentity:
        profile = "default"
    
    # Test 1: Legit path should work
    result = read_delegation_log(FakeIdentity(), path=str(legit_log))
    assert result["content"] == "Agent running..."
    
    # Test 2: Path traversal with ../.. should be blocked (403)
    evil_path = str(fake_hermes / ".." / ".." / "secret.txt")
    with pytest.raises(CoreApiError) as exc_info:
        read_delegation_log(FakeIdentity(), path=evil_path)
    assert exc_info.value.status_code == 403
    assert "Access denied" in exc_info.value.message
    
    # Test 3: Absolute path outside live dir should be blocked (403)
    with pytest.raises(CoreApiError) as exc_info:
        read_delegation_log(FakeIdentity(), path=str(secret_file))
    assert exc_info.value.status_code == 403
    
    # Test 4: Non-existent file in live dir should return 404
    fake_log = fake_hermes / "nonexistent.log"
    with pytest.raises(CoreApiError) as exc_info:
        read_delegation_log(FakeIdentity(), path=str(fake_log))
    assert exc_info.value.status_code == 404


def test_delegation_logs_lists_active_delegations(tmp_path, monkeypatch):
    """GET /api/delegation/logs returns delegation metadata."""
    fake_home = tmp_path / "fake_home"
    fake_hermes = fake_home / ".hermes" / "cache" / "delegation" / "live"
    fake_hermes.mkdir(parents=True)
    
    # Create a fake delegation directory
    deleg_dir = fake_hermes / "deleg_test123"
    deleg_dir.mkdir()
    (deleg_dir / "task-0.log").write_text("Slice 1 running...")
    (deleg_dir / "task-1.log").write_text("Slice 2 running...")
    
    # Create meta.json with goals
    import json
    meta = {
        "goals": ["Extract Chip component", "Extract Composer component"],
        "status": "running",
    }
    (deleg_dir / "meta.json").write_text(json.dumps(meta))
    
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    
    from fastapi_app.routers.file_delivery import get_delegation_logs
    
    class FakeIdentity:
        profile = "default"
    
    result = get_delegation_logs(FakeIdentity())
    
    assert "delegations" in result
    assert len(result["delegations"]) == 1
    
    deleg = result["delegations"][0]
    assert deleg["id"] == "deleg_test123"
    assert deleg["taskCount"] == 2
    assert len(deleg["logPaths"]) == 2
    assert "Extract Chip" in deleg["goals"][0]
