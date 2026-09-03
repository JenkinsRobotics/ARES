from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "install.sh"
CLI = ROOT / "bin" / "ares"
STARTER = ROOT / "start.sh"
SMOKE = ROOT / "scripts" / "smoke_clean_install.sh"


def test_root_installer_performs_real_dependency_and_frontend_install():
    source = INSTALLER.read_text(encoding="utf-8")

    assert 'pip install -r "$CONTROLLER/requirements.txt"' in source
    assert "ARES WebUI is pre-built" in source
    assert "ARES installation verified" in source
    assert "pip install -e" not in source


def test_root_installer_is_portable_and_does_not_delete_worker_state():
    source = INSTALLER.read_text(encoding="utf-8")

    assert "sed -i ''" not in source
    assert "GREEN" not in source
    assert "rm -rf" not in source
    assert "JaegerAI" not in source
    assert "$HOME/jaeger" not in source


def test_root_installer_keeps_install_source_separate_from_runtime_state():
    source = INSTALLER.read_text(encoding="utf-8")

    assert "ARES_INSTALL_DIR" in source
    assert "default: $HOME/.ares" in source
    assert "${INSTALL_DIR:-$HOME/.local/share/ares}" in source


def test_doctor_uses_requirements_instead_of_nonexistent_editable_package():
    source = CLI.read_text(encoding="utf-8")

    assert "pip install -e" not in source
    assert "requirements.txt" in source
    assert "|| true" not in "\n".join(
        line for line in source.splitlines() if "pip" in line
    )


def test_clean_install_smoke_is_isolated_and_checks_health():
    source = SMOKE.read_text(encoding="utf-8")

    assert "mktemp -d" in source
    assert 'ARES_HOME="$STATE_HOME"' in source
    assert "--no-cli --no-start --skip-native" in source
    assert 'http://127.0.0.1:$PORT/health' in source
    assert "$HOME/.ares" not in source



def test_root_installer_mounts_dashboard_static_and_fails_named_host_deps():
    source = INSTALLER.read_text(encoding="utf-8")

    assert "services/controller/apps/dashboard/static" in source
    assert "apps/web/static" not in source
    assert "Ollama is missing" in source or "require_ares_host_dependencies" in source
    assert "skipping the optional macOS application" not in source
    assert "Swift is missing" in source


def test_ares_setup_uses_jenkinsrobotics_desktop_bundle_id():
    source = CLI.read_text(encoding="utf-8")

    assert "com.jenkinsrobotics.ares-desktop" in source
    assert "com.shuwalker.ARES" not in source
    assert "services/controller/apps/dashboard/static" in source
    assert "apps/web/dist" not in source
    assert "require_ares_host_dependencies" in source


def test_default_macos_start_is_owned_by_the_menu_app():
    cli = CLI.read_text(encoding="utf-8")
    starter = STARTER.read_text(encoding="utf-8")

    assert 'open -g "$APP_PATH" --args --start-server' in cli
    assert 'exec "$SCRIPT_DIR/bin/ares" start' in starter
    assert 'ARES controller: running' in cli
