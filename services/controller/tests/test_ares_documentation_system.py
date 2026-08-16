"""Contracts for the repository-wide agent and documentation entrypoints."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]


def _read(relative: str) -> str:
    path = ROOT / relative
    assert path.exists(), f"Missing required doc: {relative}"
    return path.read_text(encoding="utf-8")


def test_cross_agent_entrypoint_routes_canonical_context():
    entrypoint = _read("AGENTS.md")
    for required in (
        "docs/vision.md",
        "docs/architecture.md",
        "docs/api.md",
        "docs/development.md",
        "apps/web/src/styles/chat-layout.css",
        "features/chat",
    ):
        assert required in entrypoint


def test_tool_specific_context_points_to_shared_entrypoint():
    assert "AGENTS.md" in _read("CLAUDE.md")
    assert "AGENTS.md" in _read("apps/macos/CLAUDE.md")
    assert "AGENTS.md" in _read("services/controller/CLAUDE.md")


def test_agents_md_has_no_banned_metaphors():
    text = _read("AGENTS.md").lower()
    for banned in ("board —", "**leo**", "hands, never", "control plane"):
        assert banned not in text


def test_web_agents_points_at_layout_css():
    web = _read("apps/web/AGENTS.md")
    assert "chat-layout.css" in web
    assert "PRODUCT_SPEC" not in web


def test_chat_and_shell_paths_exist():
    assert (ROOT / "apps/web/src/features/chat/ConversationPage.tsx").exists()
    assert (ROOT / "apps/web/src/components/shell/WorkspaceShell.tsx").exists()
    assert (ROOT / "apps/web/src/styles/chat-layout.css").exists()
    assert (ROOT / "apps/web/src/styles/shell-drawers.css").exists()
    assert not (ROOT / "apps/web/src/features/advanced-chat").exists()
    assert not (ROOT / "apps/web/src/components/command-center").exists()


def test_agent_onboarding_documents_have_no_broken_relative_links():
    documents = [
        "AGENTS.md",
        "CLAUDE.md",
        "CONTRIBUTING.md",
        "docs/README.md",
        "apps/web/AGENTS.md",
        "apps/macos/AGENTS.md",
        "services/controller/AGENTS.md",
    ]
    broken: list[str] = []
    for relative in documents:
        document = ROOT / relative
        if not document.exists():
            continue
        for raw_target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            target = raw_target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{relative} -> {raw_target}")
    assert broken == [], broken
