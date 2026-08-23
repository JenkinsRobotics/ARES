"""Tests for ARES Cognitive Operating Modes subsystem."""

import tempfile
from pathlib import Path
from core.modes import CognitiveMode, ModeManager, ModeState, DreamReport


def test_mode_state_serialization():
    state = ModeState(current_mode=CognitiveMode.FOCUS, previous_mode=CognitiveMode.STANDBY)
    d = state.as_dict()
    assert d["current_mode"] == "focus"
    assert d["previous_mode"] == "standby"
    reconstructed = ModeState.from_dict(d)
    assert reconstructed.current_mode == CognitiveMode.FOCUS
    assert reconstructed.previous_mode == CognitiveMode.STANDBY


def test_mode_aliases_and_normalization():
    from core.modes.operating_modes import normalize_mode

    assert normalize_mode("wondering") == CognitiveMode.WONDERING
    assert normalize_mode("wonder") == CognitiveMode.WONDERING
    assert normalize_mode("dream") == CognitiveMode.DREAM
    assert normalize_mode("reflect") == CognitiveMode.DREAM
    assert normalize_mode("research") == CognitiveMode.RESEARCH
    assert normalize_mode("audit") == CognitiveMode.AUDIT
    assert normalize_mode("security") == CognitiveMode.AUDIT
    assert normalize_mode("build") == CognitiveMode.FOCUS
    assert normalize_mode("idle") == CognitiveMode.STANDBY


def test_mode_manager_transitions():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "test_mode_state.json"
        mgr = ModeManager(state_file=state_file)
        assert mgr.state.current_mode == CognitiveMode.STANDBY

        # Switch to Wondering using alias 'wonder'
        mgr.switch_mode("wonder")
        assert mgr.state.current_mode == CognitiveMode.WONDERING
        assert mgr.state.previous_mode == CognitiveMode.STANDBY

        # Switch to Dream
        mgr.switch_mode("dream")
        assert mgr.state.current_mode == CognitiveMode.DREAM
        assert mgr.state.previous_mode == CognitiveMode.WONDERING

        # Switch to Research
        mgr.switch_mode("research")
        assert mgr.state.current_mode == CognitiveMode.RESEARCH

        # Switch to Audit
        mgr.switch_mode("audit")
        assert mgr.state.current_mode == CognitiveMode.AUDIT

        # Switch to Focus
        mgr.switch_mode("focus", session_id="test_sess_1")
        assert mgr.state.current_mode == CognitiveMode.FOCUS
        assert mgr.state.previous_mode == CognitiveMode.AUDIT
        assert mgr.state.active_focus_session == "test_sess_1"

        # Verify persistence on disk
        mgr2 = ModeManager(state_file=state_file)
        assert mgr2.state.current_mode == CognitiveMode.FOCUS


def test_mode_manager_dream_cycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "test_mode_state.json"
        mgr = ModeManager(state_file=state_file)

        # Create a sample workspace with a python file
        ws = Path(tmpdir) / "test_ws"
        ws.mkdir()
        (ws / "sample.py").write_text("class TestClass:\n    def test_method(self):\n        pass\n")

        report = mgr.trigger_dream_cycle([str(ws)])
        assert report.status == "completed"
        assert report.symbols_indexed >= 2
        assert report.files_analyzed >= 1
        assert mgr.state.dreams_count == 1
        assert mgr.state.last_dream_at is not None
