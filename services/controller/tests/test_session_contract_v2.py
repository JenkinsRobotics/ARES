"""Phase 2 canonical ARES↔Jaeger session ownership contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _contract():
    return {
        "version": 2,
        "ownership": {"transcript": "jaeger"},
        "operations": {
            name: {"available": True, "owner": "jaeger", "mutable": name in {
                "create", "clear", "delete",
            }}
            for name in ("create", "list", "load", "clear", "delete", "search")
        } | {
            "rename": {"available": True, "owner": "ares", "mutable": True},
            "archive": {"available": True, "owner": "ares", "mutable": True},
        },
    }


def test_shared_session_id_preserves_opaque_identifiers():
    from api.session_contract import shared_session_id

    assert shared_session_id("telegram:42") == "telegram:42"
    assert shared_session_id("shared-1") == "shared-1"


def test_gateway_emits_opaque_session_keys_without_ui_namespace():
    source = (Path(__file__).parents[1] / "api" / "gateway_chat.py").read_text(
        encoding="utf-8"
    )
    assert 'headers["X-Ares-Session-Key"] = session_id' in source
    assert 'f"webui:' not in source


def test_canonical_mutation_fails_closed_without_v2_contract(monkeypatch):
    from api.session_contract import SessionCapabilityError, require_operation

    # This test is the fail-closed contract for a SELECTED Jaeger runtime.
    # The suite-wide ARES_NO_JAEGER seam would skip the check entirely.
    monkeypatch.delenv("ARES_NO_JAEGER", raising=False)
    session = type("Session", (), {"transcript_owner": "jaeger"})()
    monkeypatch.setattr("api.session_contract.contract_for_backend", lambda _backend: None)
    with pytest.raises(SessionCapabilityError, match="v2 session contract"):
        require_operation("delete", session=session, backend="jaeger_local")


def test_ui_session_mutations_capability_requires_complete_v2_contract(monkeypatch):
    from api import ares_capabilities

    monkeypatch.setattr(
        ares_capabilities,
        "_jaeger_contract",
        lambda: ({"features": {"sessions": {
            "available": True, "contract": _contract(),
        }}}, None),
    )
    assert ares_capabilities.capabilities_for_backend("jaeger_local")["session_mutations"] is True

    monkeypatch.setattr(
        ares_capabilities,
        "_jaeger_contract",
        lambda: ({"features": {"sessions": {
            "available": True, "contract": {"version": 1, "operations": {}},
        }}}, None),
    )
    assert ares_capabilities.capabilities_for_backend("jaeger_local")["session_mutations"] is False


def test_canonical_projection_uses_jaeger_instead_of_local_transcript(monkeypatch):
    from api.models import Session
    from api.session_projection import project_session_detail

    session = Session(
        session_id="shared-1",
        messages=[{"role": "user", "content": "stale local copy", "timestamp": 1}],
        ares_backend="jaeger_local",
        transcript_owner="jaeger",
        runtime_message_count=2,
    )
    monkeypatch.setattr("api.session_contract.contract_for_backend", lambda _backend: _contract())
    monkeypatch.setattr(
        "api.session_contract.runtime_query",
        lambda operation, **_kwargs: [
            {"role": "user", "text": "canonical", "ts": 2},
            {
                "role": "assistant", "text": "done", "ts": 3,
                "metadata": {"tool_calls": [{"name": "write_file", "done": True}]},
            },
        ],
    )
    monkeypatch.setattr("api.models.get_state_db_session_messages", lambda *_a, **_k: [])

    payload = project_session_detail(session)

    assert [row["content"] for row in payload["messages"]] == ["canonical", "done"]
    assert payload["tool_calls"] == [
        {"name": "write_file", "done": True, "assistant_msg_idx": 1},
    ]
    assert "stale local copy" not in json.dumps(payload)


def test_canonical_session_sidecar_persists_metadata_without_messages(tmp_path, monkeypatch):
    from api.models import Session

    monkeypatch.setattr("api.config.SESSION_DIR", tmp_path)
    monkeypatch.setattr("api.models.SESSION_DIR", tmp_path)
    monkeypatch.setattr("api.models._write_session_index", lambda **_kwargs: None)
    session = Session(
        session_id="shared-1",
        messages=[{"role": "user", "content": "runtime owned"}],
        tool_calls=[{"name": "write_file"}],
        transcript_owner="jaeger",
        runtime_message_count=1,
    )

    session.save()
    stored = json.loads((tmp_path / "shared-1.json").read_text(encoding="utf-8"))

    assert stored["messages"] == []
    assert stored["tool_calls"] == []
    assert stored["message_count"] == 1
    assert stored["transcript_owner"] == "jaeger"


def test_create_chat_reload_rename_archive_restart_delete_restart(tmp_path, monkeypatch):
    """Full Phase 2 durability sequence with separate runtime/UI stores."""
    from api.models import Session
    from api.session_projection import project_session_detail

    ui_dir = tmp_path / "ares-ui"
    ui_dir.mkdir()
    runtime_path = tmp_path / "jaeger-runtime.json"
    tombstone_path = tmp_path / "jaeger-tombstones.json"
    monkeypatch.setattr("api.config.SESSION_DIR", ui_dir)
    monkeypatch.setattr("api.models.SESSION_DIR", ui_dir)
    monkeypatch.setattr("api.models._write_session_index", lambda **_kwargs: None)
    monkeypatch.setattr("api.session_contract.contract_for_backend", lambda _backend: _contract())

    session_id = "lifecycle-1"
    runtime_path.write_text(json.dumps({session_id: []}), encoding="utf-8")
    session = Session(
        session_id=session_id,
        ares_backend="jaeger_local",
        transcript_owner="jaeger",
        runtime_message_count=0,
    )
    session.save()  # create

    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime[session_id] = [
        {"role": "user", "text": "hello", "ts": 1},
        {"role": "assistant", "text": "hi", "ts": 2},
    ]
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")  # chat
    session.runtime_message_count = 2
    session.save()

    monkeypatch.setattr(
        "api.session_contract.runtime_query",
        lambda operation, **_kwargs: json.loads(runtime_path.read_text(encoding="utf-8"))[session_id],
    )
    reloaded = Session.load(session_id)  # reload
    assert reloaded.messages == []
    assert [m["content"] for m in project_session_detail(reloaded)["messages"]] == ["hello", "hi"]

    reloaded.title = "Renamed in ARES"  # rename
    reloaded.manual_title = True
    reloaded.archived = True  # archive
    reloaded.save(touch_updated_at=False)
    restarted = Session.load(session_id)  # restart
    assert restarted.title == "Renamed in ARES"
    assert restarted.archived is True
    assert restarted.messages == []

    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime.pop(session_id, None)
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    tombstone_path.write_text(json.dumps({session_id: True}), encoding="utf-8")
    restarted.path.unlink()  # delete

    assert Session.load(session_id) is None  # restart after delete
    assert session_id not in json.loads(runtime_path.read_text(encoding="utf-8"))
    assert json.loads(tombstone_path.read_text(encoding="utf-8"))[session_id] is True
