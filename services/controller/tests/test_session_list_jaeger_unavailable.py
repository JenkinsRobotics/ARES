"""Sidebar listing must survive a Jaeger runtime that cannot boot.

Selecting an unconfigured cloud model used to 500 GET /api/sessions because
the list path required Jaeger ``list_sessions`` to succeed. The WebUI then
looked empty even though ARES still had the projection rows.
"""

from __future__ import annotations

from api.providers.jaeger.bridge_client import JaegerError
from api.session_contract import SessionCapabilityError
from fastapi_app.services import AresCoreService


def _jaeger_row(**overrides):
    row = {
        "session_id": "sid-jaeger-1",
        "title": "hi",
        "profile": "default",
        "message_count": 12,
        "updated_at": 20,
        "last_message_at": 20,
        "ares_backend": "jaeger_local",
        "transcript_owner": "jaeger",
        "source_tag": "webui",
        "pinned": False,
        "archived": False,
    }
    row.update(overrides)
    return row


def _patch_listing(monkeypatch, *, runtime_query):
    import api.models as models
    import api.profiles as profiles
    import api.session_contract as session_contract

    monkeypatch.setattr("api.config.load_settings", lambda: {"show_cli_sessions": False})
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")
    monkeypatch.setattr(models, "all_sessions", lambda diag=None: [_jaeger_row()])
    monkeypatch.setattr(session_contract, "backend_for_session", lambda session=None: "jaeger_local")
    monkeypatch.setattr(session_contract, "runtime_owns_transcript", lambda session, backend=None: True)
    monkeypatch.setattr(session_contract, "require_operation", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_contract, "runtime_query", runtime_query)
    # services.py imports these names inside the method; patch the modules
    # they bind from so the local names resolve to the doubles.
    monkeypatch.setattr("api.session_contract.backend_for_session", lambda session=None: "jaeger_local")
    monkeypatch.setattr("api.session_contract.runtime_owns_transcript", lambda session, backend=None: True)
    monkeypatch.setattr("api.session_contract.require_operation", lambda *args, **kwargs: None)
    monkeypatch.setattr("api.session_contract.runtime_query", runtime_query)


def test_sessions_list_survives_jaeger_model_boot_failure(monkeypatch):
    def boom(*_args, **_kwargs):
        raise JaegerError(
            "selected model cannot serve — provider 'openai', model 'gpt-5.4-mini': "
            "not configured — provider 'openai' needs an API key"
        )

    _patch_listing(monkeypatch, runtime_query=boom)
    payload = AresCoreService().sessions(
        profile="default", exclude_hidden=False, include_archived=False
    )
    rows = payload["sessions"]
    assert len(rows) == 1
    assert rows[0]["session_id"] == "sid-jaeger-1"
    assert rows[0]["runtime_missing"] is True
    assert rows[0]["message_count"] == 12


def test_sessions_list_survives_session_capability_error(monkeypatch):
    def boom(*_args, **_kwargs):
        raise SessionCapabilityError("list is unavailable")

    _patch_listing(monkeypatch, runtime_query=boom)
    payload = AresCoreService().sessions(
        profile="default", exclude_hidden=False, include_archived=False
    )
    assert payload["sessions"][0]["runtime_missing"] is True


def test_empty_state_db_does_not_look_like_an_old_agent(tmp_path):
    from api.agent_sessions import read_importable_agent_session_rows

    empty = tmp_path / "state.db"
    empty.write_bytes(b"")
    assert read_importable_agent_session_rows(empty) == []
