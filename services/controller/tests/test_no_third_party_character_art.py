"""No third-party character art ships in this repository.

Fourteen PNGs of recognisable owned characters — GLaDOS, HAL 9000, Anakin
Skywalker, Bender, Eren Yeager, Lelouch, Paul Atreides, TARS, JARVIS, Kamina,
Simon, a Helldiver — were tracked under the macOS app's resources and bundled
into the shipped product by SwiftPM's `.process("Resources")`. Nothing in the
codebase referenced them: character personas come from JaegerAI at runtime, the
API falls back to `ares-app-icon.png`, and the browser's `<img onerror>`
handlers hide a card whose art fails to load.

So they were 2.4 MB of dead weight that also happened to be other people's
intellectual property, redistributed under AGPL-3.0. A private prototype can
carry that; a public repository cannot.

Persona art belongs to whoever supplies the persona. If ARES ever ships its
own, it must be originally created or carry a license recorded in
`THIRD_PARTY.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".tiff", ".bmp"}

# Names that identify a character owned by someone else. Matched against the
# file stem, so `glados.png` and `glados@2x.png` both trip it.
OWNED_CHARACTER_NAMES = frozenset({
    "anakin", "anakin_skywalker", "bender", "eren", "eren_yeager", "glados",
    "hal_9000", "hal9000", "helldiver", "jarvis", "kamina", "lelouch",
    "paul_atreides", "simon", "tars",
})

# Directories that must not become a home for bundled persona art again.
FORBIDDEN_ART_DIRS = (
    Path("apps/macos/Sources/ARES/Resources/Characters"),
    Path("apps/web/static/characters"),
)


def _tracked_images() -> list[Path]:
    """Every image in the working tree, excluding build output and vendor."""
    skip_parts = {".git", ".venv", ".build", "node_modules", "vendor", "__pycache__"}
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
            continue
        parts = path.relative_to(ROOT).parts
        if skip_parts & set(parts):
            continue
        # Built .app bundles are output, not source: they carry whatever the
        # last build put there, so a stale bundle would fail this forever even
        # after the source is clean. Rebuilding regenerates them from source,
        # which is what this test actually governs.
        if any(part.endswith(".app") for part in parts):
            continue
        found.append(path.relative_to(ROOT))
    return found


@pytest.mark.parametrize(
    "directory", FORBIDDEN_ART_DIRS, ids=lambda p: p.as_posix()
)
def test_bundled_persona_art_directory_does_not_exist(directory):
    path = ROOT / directory
    if not path.exists():
        return
    images = [item.name for item in path.iterdir() if item.suffix.lower() in IMAGE_SUFFIXES]
    assert images == [], (
        f"{directory} carries bundled persona art again: {sorted(images)}. "
        "Persona art comes from the agent that defines the persona; anything "
        "shipped here must be original or licensed in THIRD_PARTY.md."
    )


def test_no_image_is_named_after_someone_elses_character():
    offenders: list[str] = []
    for relative in _tracked_images():
        stem = relative.stem.lower().split("@")[0]
        if stem in OWNED_CHARACTER_NAMES:
            offenders.append(relative.as_posix())
    assert offenders == [], (
        "Third-party character art in a public AGPL repository:\n  "
        + "\n  ".join(offenders)
        + "\nReplace it with original artwork, or let users supply their own."
    )


def test_the_api_still_has_a_fallback_when_a_persona_has_no_art():
    """Removing the art must not leave character cards broken.

    `characters.py` normalises every row to a `card_url`, defaulting to the
    app icon, and the browser hides an image that fails to load. Both halves
    have to stay true or deleting bundled art becomes a visual regression.
    """
    from api.characters import _normalize

    row = _normalize({"id": "someone", "name": "Someone"})
    assert row["card_url"], "a persona with no art must still get a card_url"

    characters_js = (ROOT / "apps/web/static/characters.js").read_text(encoding="utf-8")
    assert "onerror" in characters_js, (
        "characters.js no longer guards against art that fails to load"
    )
