"""Attribution files exist and still cover what actually ships.

ARES is AGPL-3.0 and derived from MIT-licensed work, so the upstream notices
have to travel with the code. That is an obligation, not a courtesy, and it is
the kind that rots quietly: a vendored library gets upgraded, a directory gets
renamed, and the notice that made redistribution lawful is no longer beside the
code it covers.

These tests are deliberately about presence and coverage rather than wording.
"""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
VENDOR = ROOT / "apps" / "web" / "static" / "vendor"

REQUIRED_NOTICES = (
    Path("LICENSE"),
    Path("THIRD_PARTY.md"),
    Path("apps/web/static/LICENSE"),
    Path("services/controller/LICENSE"),
    Path("apps/web/static/vendor/LICENSES.md"),
)


@pytest.mark.parametrize("relative", REQUIRED_NOTICES, ids=lambda p: p.as_posix())
def test_required_notice_file_exists_and_is_not_empty(relative):
    path = ROOT / relative
    assert path.is_file(), f"{relative} is missing"
    assert path.read_text(encoding="utf-8").strip(), f"{relative} is empty"


def test_the_donated_surfaces_carry_the_upstream_mit_notice():
    """Both forked trees keep the Hermes WebUI copyright line beside the code."""
    for relative in (Path("apps/web/static/LICENSE"), Path("services/controller/LICENSE")):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "MIT License" in text, f"{relative} is not the MIT text"
        assert "Hermes Web UI Contributors" in text, (
            f"{relative} lost the upstream copyright line — that line is the "
            "condition under which this code may be redistributed"
        )


def test_root_license_is_still_agpl():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text


def test_every_vendored_library_has_a_recorded_notice():
    """A library added to vendor/ without a notice is an unlicensed redistribution.

    Minified builds routinely strip their license banner, so the notice cannot
    be assumed to live in the shipped file — vendor/LICENSES.md is where it has
    to be recorded.
    """
    if not VENDOR.is_dir():
        pytest.skip("no vendored libraries")
    notices = (VENDOR / "LICENSES.md").read_text(encoding="utf-8").lower()

    undocumented: list[str] = []
    for entry in sorted(VENDOR.iterdir()):
        if entry.name == "LICENSES.md":
            continue
        # Directory (katex/, js-yaml/) or single file (smd.min.js) — the
        # library's name is the stem either way.
        library = entry.name.split(".")[0].lower()
        if library not in notices:
            undocumented.append(entry.name)

    assert undocumented == [], (
        "Vendored without a recorded notice — add it to "
        "apps/web/static/vendor/LICENSES.md with its upstream license:\n  "
        + "\n  ".join(undocumented)
    )


def test_third_party_index_points_at_notices_that_exist():
    """Every path THIRD_PARTY.md cites as holding a notice must be real."""
    text = (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    cited = {
        "apps/web/static/LICENSE",
        "services/controller/LICENSE",
        "apps/web/static/vendor/LICENSES.md",
    }
    missing_from_doc = [path for path in cited if path not in text]
    assert missing_from_doc == [], f"THIRD_PARTY.md no longer cites {missing_from_doc}"
    broken = [path for path in cited if not (ROOT / path).is_file()]
    assert broken == [], f"THIRD_PARTY.md cites files that do not exist: {broken}"
