"""A resent identical message must survive stale-stream repair.

When a turn hangs, the user's near-universal response is to send the same
words again. Stale-stream repair decided whether the pending turn was
already stored by comparing the newest user row's TEXT to the pending
text — so the resend matched the previous turn, repair concluded it was
"already checkpointed", skipped the append, and then cleared
``pending_user_message``. The resent turn reached neither the transcript
nor the model. From the user's side the message simply vanished.

The turn's timestamp is what identifies it: both writers of a legitimate
existing copy (the eager-save checkpoint and the recovered-turn append)
stamp it with ``int(pending_started_at)``. These tests pin both
directions — a genuine resend is kept, an already-stored turn is still
not duplicated.
"""

import time

import pytest

import api.config as config
import api.models as models
import api.streaming as streaming
from api.models import Session
from api.session_runtime_state import clear_stale_stream_state


@pytest.fixture(autouse=True)
def _isolate_sessions(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    index_file = session_dir / "_index.json"
    monkeypatch.setattr(models, "SESSION_DIR", session_dir)
    monkeypatch.setattr(models, "SESSION_INDEX_FILE", index_file)
    monkeypatch.setattr(streaming, "SESSION_DIR", session_dir)
    monkeypatch.setattr(config, "SESSION_INDEX_FILE", index_file, raising=False)
    for store in (models.SESSIONS, config.STREAMS, config.ACTIVE_RUNS,
                  config.SESSION_AGENT_LOCKS):
        store.clear()
    yield
    for store in (models.SESSIONS, config.STREAMS, config.ACTIVE_RUNS,
                  config.SESSION_AGENT_LOCKS):
        store.clear()


def _stale_session(sid, messages, pending, started_at):
    """A session whose stream is dead and whose pending turn is past grace."""
    s = Session(session_id=sid, title="t", messages=list(messages))
    s.active_stream_id = "dead-stream"
    s.pending_user_message = pending
    s.pending_started_at = started_at
    s.save()
    models.SESSIONS[sid] = s
    return s


def _user_texts(session):
    return [m.get("content") for m in session.messages if m.get("role") == "user"]


def test_distinct_pending_message_is_materialized():
    """Control: nothing about this change may affect the ordinary path."""
    started = time.time() - 3600
    s = _stale_session(
        "distinct",
        [{"role": "user", "content": "first", "timestamp": int(started - 60)}],
        "second",
        started,
    )
    clear_stale_stream_state(s)
    assert "second" in _user_texts(s)


def test_resent_identical_message_is_not_swallowed():
    """The regression: same text, EARLIER timestamp, so it is a new turn."""
    first_ts = int(time.time() - 3600)
    resend_started = time.time() - 1800
    s = _stale_session(
        "resend",
        [{"role": "user", "content": "run the build", "timestamp": first_ts}],
        "run the build",
        resend_started,
    )
    clear_stale_stream_state(s)
    kept = [t for t in _user_texts(s) if t == "run the build"]
    assert len(kept) == 2, f"the resent turn was dropped: {_user_texts(s)}"


def test_already_checkpointed_turn_is_not_duplicated():
    """The other direction: a row carrying THIS turn's timestamp is the
    eager-save checkpoint of the pending turn and must not be appended
    twice."""
    started = time.time() - 3600
    s = _stale_session(
        "checkpointed",
        [{"role": "user", "content": "deploy it", "timestamp": int(started)}],
        "deploy it",
        started,
    )
    clear_stale_stream_state(s)
    kept = [t for t in _user_texts(s) if t == "deploy it"]
    assert len(kept) == 1, f"the checkpointed turn was duplicated: {_user_texts(s)}"
