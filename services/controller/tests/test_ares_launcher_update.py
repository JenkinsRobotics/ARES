"""Source contract for the user-facing `ares update` workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "bin" / "ares"


def test_update_builds_and_verifies_installed_app_bundle():
    source = LAUNCHER.read_text(encoding="utf-8")
    update = source[source.index("cmd_update()") : source.index('case "${cmd}"')]

    assert 'bash ./build-app.sh' in update
    assert '${HOME}/Applications/ARES.app/Contents/MacOS/ARES' in update
    assert "swift build &&" not in update


def test_plain_start_does_not_rebuild_on_every_launch():
    source = LAUNCHER.read_text(encoding="utf-8")
    start_case = source[source.index("case \"${cmd}\"") :]

    assert "_launch_ares_app" in start_case
    assert "build-app.sh" not in start_case


def test_app_launch_hands_off_managed_standalone_controller():
    source = LAUNCHER.read_text(encoding="utf-8")
    launch = source[source.index("_launch_ares_app()") : source.index("cmd_setup()")]

    assert '[[ "$(_ares_runtime_owner)" == "standalone" ]]' in launch
    assert 'bash "${CTL_SCRIPT}" stop' in launch
    assert "controller did not release port" in launch
    assert '== "mac_app"' not in launch
