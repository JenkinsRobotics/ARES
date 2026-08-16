"""Standing behavioral directives: storage, injection, and honest scope.

Directives are prepended to the execution prompt of every turn, on every
worker. Two properties matter most and are pinned here: they must reach the
worker, and they must never leak into what ARES persists as the user's own
message.
"""
from __future__ import annotations

import pytest

from api import ares_directives

# Captured before any test patches it, so the end-to-end cases can restore the
# genuine loader after the shared runtime fixture stubs it out.
_REAL_LOADER = ares_directives.load_active_directives


@pytest.fixture
def ares_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_HOME", str(tmp_path))
    return tmp_path


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ── loading ──────────────────────────────────────────────────────────────────


def test_missing_file_yields_no_directives(ares_home):
    state = ares_directives.read_directives_file()
    assert state["enabled"] is False
    assert state["directives"] == []
    assert ares_directives.load_active_directives() == []


def test_disabled_file_yields_no_active_directives(ares_home):
    _write(
        ares_directives.directives_path(),
        "directives:\n  - Reply in 10 words or less\nenabled: false\n",
    )
    state = ares_directives.read_directives_file()
    assert state["directives"] == ["Reply in 10 words or less"]  # still stored
    assert ares_directives.load_active_directives() == []  # but not in force


def test_enabled_file_yields_directives_in_order(ares_home):
    _write(
        ares_directives.directives_path(),
        "directives:\n  - One\n  - Two\n  - Three\nenabled: true\n",
    )
    assert ares_directives.load_active_directives() == ["One", "Two", "Three"]


def test_malformed_file_degrades_instead_of_breaking_turns(ares_home):
    """A bad edit must not take chat down — this is on the turn hot path."""
    _write(ares_directives.directives_path(), "directives: [unclosed\n  - broken:\n:::\n")
    assert ares_directives.load_active_directives() == []


def test_non_mapping_file_is_ignored(ares_home):
    _write(ares_directives.directives_path(), "- just\n- a\n- list\n")
    assert ares_directives.load_active_directives() == []


def test_directive_count_and_length_are_bounded(ares_home):
    many = "\n".join(f"  - rule {i}" for i in range(ares_directives.MAX_DIRECTIVES + 25))
    _write(ares_directives.directives_path(), f"directives:\n{many}\nenabled: true\n")
    assert len(ares_directives.load_active_directives()) == ares_directives.MAX_DIRECTIVES


def test_overlong_directive_is_truncated(ares_home):
    _write(
        ares_directives.directives_path(),
        "directives:\n  - " + ("x" * 5000) + "\nenabled: true\n",
    )
    (only,) = ares_directives.load_active_directives()
    assert len(only) == ares_directives.MAX_DIRECTIVE_CHARS


# ── rendering and injection ──────────────────────────────────────────────────


def test_empty_directives_render_to_nothing():
    assert ares_directives.directives_block([]) == ""


def test_block_labels_the_rules_and_lists_each_one():
    block = ares_directives.directives_block(["No markdown", "Be brief"])
    assert block.startswith(ares_directives.BLOCK_HEADER)
    assert block.endswith(ares_directives.BLOCK_FOOTER)
    assert "- No markdown" in block
    assert "- Be brief" in block


def test_apply_directives_prepends_and_preserves_the_prompt(ares_home):
    _write(
        ares_directives.directives_path(),
        "directives:\n  - No markdown\nenabled: true\n",
    )
    out = ares_directives.apply_directives("What is 2+2?")
    assert out.startswith(ares_directives.BLOCK_HEADER)
    assert out.endswith("What is 2+2?")
    assert "- No markdown" in out


def test_apply_directives_is_a_noop_when_disabled(ares_home):
    _write(ares_directives.directives_path(), "directives:\n  - X\nenabled: false\n")
    assert ares_directives.apply_directives("hello") == "hello"


def test_apply_directives_never_raises_on_a_broken_store(ares_home, monkeypatch):
    def _boom():
        raise RuntimeError("disk gone")

    monkeypatch.setattr(ares_directives, "load_active_directives", _boom)
    assert ares_directives.apply_directives("hello") == "hello"


# ── persistence ──────────────────────────────────────────────────────────────


def test_save_then_load_round_trips(ares_home):
    ares_directives.save_directives(["Alpha", "Beta"], enabled=True)
    assert ares_directives.load_active_directives() == ["Alpha", "Beta"]
    assert ares_directives.directives_path().exists()


def test_saving_disabled_keeps_rules_but_stops_injecting(ares_home):
    ares_directives.save_directives(["Alpha"], enabled=False)
    assert ares_directives.read_directives_file()["directives"] == ["Alpha"]
    assert ares_directives.load_active_directives() == []


def test_save_normalizes_whitespace_and_drops_blanks(ares_home):
    ares_directives.save_directives(["  spaced   out  ", "", "   ", "ok"], enabled=True)
    assert ares_directives.load_active_directives() == ["spaced out", "ok"]


# ── glass box ────────────────────────────────────────────────────────────────


def test_summary_separates_stored_from_active(ares_home):
    ares_directives.save_directives(["A", "B"], enabled=False)
    summary = ares_directives.directives_summary()
    assert summary["stored_count"] == 2
    assert summary["active_count"] == 0
    assert summary["enabled"] is False


def test_summary_states_that_model_election_is_not_covered(ares_home):
    """The count must not imply more control than directives actually have."""
    summary = ares_directives.directives_summary()
    assert summary["scope"] == "behavioral"
    assert "model" in summary["note"].lower()


# ── the property that protects history ───────────────────────────────────────


def test_injection_target_is_the_prompt_not_the_persisted_message(ares_home):
    """Directives ride the execution prompt; history keeps the typed text.

    ``start_session_turn`` persists ``clean_message`` and sends
    ``apply_directives(context_message)``. If those ever converge, the user's
    transcript starts showing injected rules as things they said.
    """
    _write(ares_directives.directives_path(), "directives:\n  - Be brief\nenabled: true\n")

    typed = "What is 2+2?"
    execution_prompt = ares_directives.apply_directives(f"[context]\n\n{typed}")

    assert ares_directives.BLOCK_HEADER in execution_prompt
    assert ares_directives.BLOCK_HEADER not in typed
    assert typed in execution_prompt


# ── end-to-end through the real turn seam ────────────────────────────────────


def _capture_turn(monkeypatch, ares_home, *, is_gateway: bool):
    """Run start_session_turn with a recording worker; return the prompt sent."""
    import threading
    from types import SimpleNamespace

    from api import chat_runtime
    from tests.test_chat_runtime import _isolate_runtime, _session

    session = _session()
    _isolate_runtime(monkeypatch, session)
    # _isolate_runtime disables directives so unrelated prompt tests do not
    # depend on the developer's ~/.ares. Put the real loader back — reading the
    # tmp ARES_HOME this fixture set — since directives are what we are testing.
    monkeypatch.setattr("api.ares_directives.load_active_directives", _REAL_LOADER)

    captured: dict = {}

    def worker(session_id, prompt, model, workspace, stream_id, attachments, **kwargs):
        captured["prompt"] = prompt

    class ImmediateThread:
        def __init__(self, *, target, args, kwargs, **_rest):
            self._call = (target, args, kwargs)

        def start(self):
            target, args, kwargs = self._call
            target(*args, **kwargs)

    monkeypatch.setattr(chat_runtime.threading, "Thread", ImmediateThread)

    backend = SimpleNamespace(
        name="jaeger_local",
        get_worker_target=lambda: (worker, is_gateway, False),
    )
    chat_runtime.start_session_turn(
        session.session_id, "What is 2+2?", source="webui", backend=backend
    )
    return captured.get("prompt", ""), session


@pytest.mark.parametrize("is_gateway", [False, True])
def test_directives_reach_the_worker_on_both_prompt_shapes(ares_home, monkeypatch, is_gateway):
    """Gateway workers skip build_context_prompt, so injection cannot live there."""
    _write(ares_directives.directives_path(), "directives:\n  - Be brief\nenabled: true\n")

    prompt, _ = _capture_turn(monkeypatch, ares_home, is_gateway=is_gateway)

    assert ares_directives.BLOCK_HEADER in prompt
    assert "- Be brief" in prompt
    assert "What is 2+2?" in prompt


def test_disabling_directives_changes_the_next_prompt(ares_home, monkeypatch):
    _write(ares_directives.directives_path(), "directives:\n  - Be brief\nenabled: true\n")
    with_directives, _ = _capture_turn(monkeypatch, ares_home, is_gateway=False)

    _write(ares_directives.directives_path(), "directives:\n  - Be brief\nenabled: false\n")
    without_directives, _ = _capture_turn(monkeypatch, ares_home, is_gateway=False)

    assert ares_directives.BLOCK_HEADER in with_directives
    assert ares_directives.BLOCK_HEADER not in without_directives
    assert len(with_directives) > len(without_directives)


def test_injected_directives_never_enter_session_history(ares_home, monkeypatch):
    """The user's transcript must show what they typed, not the rules."""
    _write(ares_directives.directives_path(), "directives:\n  - Be brief\nenabled: true\n")

    prompt, session = _capture_turn(monkeypatch, ares_home, is_gateway=False)
    assert ares_directives.BLOCK_HEADER in prompt

    assert session.pending_user_message == "What is 2+2?"
    for message in list(getattr(session, "messages", None) or []):
        assert ares_directives.BLOCK_HEADER not in str(message.get("content", ""))
