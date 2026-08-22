"""Regression checks for ARES tab ownership and Jaeger runtime mapping."""

from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[3] / "apps" / "web" / "static"


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def test_tasks_do_not_depend_on_messaging_gateway() -> None:
    panels = _read("panels.js")
    index = _read("index.html")

    assert "loadCronGatewayNotice" not in panels
    assert "_cronGatewayNoticeHtml" not in panels
    assert 'id="cronGatewayNotice"' not in index
    assert "scheduled jobs require the Hermes gateway" not in panels


def test_visible_runtime_labels_do_not_send_users_back_to_hermes() -> None:
    index = _read("index.html")
    panels = _read("panels.js")
    ui = _read("ui.js")

    assert "https://get-hermes.ai/" not in index
    assert "https://github.com/nesquena/hermes-webui/issues" not in index
    assert "Hermes profiles" not in panels
    assert "Hermes agent is not responding" not in index
    assert "Hermes agent is not responding" not in ui


def test_composer_exposes_agent_mode_and_slash_command_browser() -> None:
    index = _read("index.html")
    commands = _read("commands.js")

    assert 'id="composerModeChip"' in index
    assert 'data-mode="plan"' in index
    assert 'data-mode="manual"' in index
    assert 'data-mode="auto"' in index
    assert 'id="btnSlashCommands"' in index
    assert 'id="slashCommandsPopup"' in index
    assert "function setAgentMode" in commands
    assert "function toggleSlashCommandsPopup" in commands
    assert "function applyAgentModeToOutboundMessage" in commands


def test_dashboard_handler_exposes_only_the_ares_name() -> None:
    ui = _read("ui.js")

    assert "function openExternalDashboard(event)" in ui
    assert "const openARESDashboard=openExternalDashboard" in ui
    assert "openHermesDashboard" not in ui
