"""Static contract for the ARES-owned Dispatcher projection."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "apps" / "web" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_dispatcher_is_a_first_class_current_ui_panel() -> None:
    index = _read("index.html")
    panels = _read("panels.js")

    assert index.count('data-panel="dispatcher"') == 2
    assert 'id="panelDispatcher"' in index
    assert 'id="mainDispatcher"' in index
    assert 'id="dispatcherTimeline"' in index
    assert 'id="dispatcherApprovalState"' in index
    assert 'id="dispatcherOutputs"' in index
    assert 'id="dispatcherGitState"' in index
    assert 'id="dispatcherRecoveryCard"' in index
    assert 'id="dispatcherEvidence"' in index
    assert 'static/dispatcher.js' in index
    assert 'static/dispatcher.css' in index
    assert "'dispatcher'" in panels
    assert "loadDispatcher" in panels


def test_dispatcher_projects_current_ares_contracts() -> None:
    script = _read("dispatcher.js")

    assert "cloneNode(true)" in script  # current rendered Worklog projection
    assert "/api/approval/pending" in script
    assert "collectSessionArtifacts" in script
    assert "/api/git/status?session_id=" in script
    assert "/api/ares/verification-evidence" in script
    assert "_aresCapabilityPayload" in script
    assert "switchPanel(name)" in script
    assert "/api/session/pin" in script


def test_dispatcher_does_not_claim_runtime_ownership() -> None:
    script = _read("dispatcher.js")

    assert "does not own a transcript" in script
    assert "/api/dispatch/turn" not in script
    assert "keepAlive" not in script
    assert "mobileNotifs" not in script
    assert "SpeechRecognition" not in script


def test_dispatcher_reuses_canonical_recovery_paths() -> None:
    script = _read("dispatcher.js")

    assert "cmdRetry()" in script
    assert "cmdUndo()" in script
    assert "typeof send!=='function'" in script
    assert "/api/session/retry" not in script
    assert "/api/session/undo" not in script
    assert "[halted:" in script


def test_dispatcher_assets_are_available_offline() -> None:
    service_worker = _read("sw.js")

    assert "./static/dispatcher.js" in service_worker
    assert "./static/dispatcher.css" in service_worker
