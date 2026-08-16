from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "install.sh"
CLI = ROOT / "bin" / "ares"
SMOKE = ROOT / "scripts" / "smoke_clean_install.sh"


def test_root_installer_performs_real_dependency_and_frontend_install():
    source = INSTALLER.read_text(encoding="utf-8")

    assert 'pip install -r "$CONTROLLER/requirements.txt"' in source
    assert "Hermes vanilla UI is pre-built" in source
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
