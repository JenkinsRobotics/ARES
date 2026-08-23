"""A reader who scrolls up mid-stream stays where they put themselves.

Reproduced in a live browser against the running WebUI: with a stream
appending tokens, scrolling up correctly unpinned auto-follow — and the very
next token yanked the viewport back to the bottom and re-pinned it, leaving the
contradictory state ``_scrollPinned === true`` WITH
``_messageUserUnpinned === true``. Repeat once per token for the length of the
turn and the transcript is unscrollable until the tab is reloaded.

The cause was a half-applied guard. ``_setMessageScrollToBottom()`` has two
halves: a synchronous write, and a ``requestAnimationFrame`` retry for late
layout growth. The retry checked ``_messageUserUnpinned`` and documented why —
"under the sticky-unpin model (#3343) _messageUserUnpinned is the authoritative
'user scrolled away' signal, so DON'T snap them back or re-pin if so". The
synchronous half had no such check, and
``_settleMessageScrollToBottom()`` calls straight into it on every token
("Sync write anchors the viewport immediately").

These assertions are on source structure rather than behaviour because the
behaviour needs a live browser: the scroll listener's logic runs inside a
``requestAnimationFrame``, which does not fire in a headless or backgrounded
page. Structure is what regresses here anyway — the bug was one missing guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
UI_JS = ROOT / "apps" / "web" / "static" / "ui.js"


@pytest.fixture(scope="module")
def ui_source() -> str:
    return UI_JS.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    """The CODE of ``function name(...)``, with `//` comments stripped.

    Comments are removed because these assertions compare the ORDER of
    statements, and this file's own explanatory comments quote the very
    identifiers being searched for. Matching a mention inside a comment would
    make the test pass or fail on prose.
    """
    start = source.index(f"function {name}(")
    following = source.find("\nfunction ", start + 1)
    body = source[start:following if following != -1 else len(source)]
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("//")
    )


def test_the_synchronous_bottom_write_checks_the_unpin_flag(ui_source):
    """The actual fix.

    The guard must sit BEFORE the scrollTop write, not only in the rAF retry.
    """
    body = _function_body(ui_source, "_setMessageScrollToBottom")

    guard = body.index("if(_messageUserUnpinned)")
    first_write = body.index("el.scrollTop=el.scrollHeight")
    assert guard < first_write, (
        "_setMessageScrollToBottom writes scrollTop before checking "
        "_messageUserUnpinned — a reader who scrolled up mid-stream will be "
        "yanked back to the bottom by the next streamed token"
    )


def test_the_synchronous_half_does_not_repin_an_unpinned_reader(ui_source):
    """``_scrollPinned=true`` must not run when the reader scrolled away.

    Re-pinning while ``_messageUserUnpinned`` stays true produces a
    contradictory state that no later code can reason about correctly.
    """
    body = _function_body(ui_source, "_setMessageScrollToBottom")
    guard = body.index("if(_messageUserUnpinned)")
    first_repin = body.index("_scrollPinned=true")
    assert guard < first_repin


def test_the_guard_releases_the_programmatic_scroll_latch(ui_source):
    """Bailing out must not strand ``_programmaticScroll``.

    That latch makes the scroll listener ignore events as self-inflicted. Left
    set, a real user scroll would be discarded — trading one scroll bug for a
    subtler one.
    """
    body = _function_body(ui_source, "_setMessageScrollToBottom")
    guard_at = body.index("if(_messageUserUnpinned)")
    tail = body[guard_at:guard_at + 400]
    assert "_deferClearProgrammaticScroll()" in tail
    assert tail.index("_deferClearProgrammaticScroll()") < tail.index("return")


def test_the_rafretry_guard_is_still_there(ui_source):
    """The half that was always correct must stay correct."""
    body = _function_body(ui_source, "_setMessageScrollToBottom")
    assert body.count("_messageUserUnpinned") >= 2, (
        "the rAF retry lost its sticky-unpin guard"
    )


def test_explicit_jumps_clear_the_flag_before_scrolling(ui_source):
    """Why guarding on the flag is safe.

    ``scrollToBottom()`` is a deliberate user action (End button, jump-to-latest)
    and must still work from anywhere in the transcript. It clears
    ``_messageUserUnpinned`` first, so the new guard never blocks it. If that
    ordering is ever reversed, the End button silently stops working.
    """
    body = _function_body(ui_source, "scrollToBottom")
    clears = body.index("_messageUserUnpinned=false")
    settles = body.index("_settleMessageScrollToBottom")
    assert clears < settles, (
        "scrollToBottom() no longer clears the sticky-unpin flag before "
        "settling — the End button will be blocked by the guard in "
        "_setMessageScrollToBottom"
    )


def test_settle_still_drives_the_synchronous_write(ui_source):
    """Guards the assumption the whole fix rests on.

    If ``_settleMessageScrollToBottom`` stopped calling straight into
    ``_setMessageScrollToBottom``, the guard above would be protecting a path
    that no longer runs, and the real yank would move somewhere unguarded.
    """
    body = _function_body(ui_source, "_settleMessageScrollToBottom")
    assert re.search(r"_setMessageScrollToBottom\(\)\s*;", body), (
        "_settleMessageScrollToBottom no longer performs the synchronous "
        "bottom write — re-check where the streaming follow now writes"
    )
