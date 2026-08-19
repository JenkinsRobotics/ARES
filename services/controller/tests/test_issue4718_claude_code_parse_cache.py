"""Regression tests for the Claude Code transcript parse cache (#4718/#4662).

The sidebar/profile-switch cold path was dominated by re-parsing every Claude
Code JSONL transcript on each /api/sessions build. ``_parse_claude_code_jsonl``
is now memoized by the file's (path, mtime_ns, size) so a warm build re-stats
instead of re-parsing, while any genuine edit transparently invalidates just
the changed file. These tests pin that behavior.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _rows(text: str = "hello") -> list:
    return [
        {"summary": "Cache QA"},
        {"timestamp": "2026-04-18T12:00:01Z", "message": {"role": "user", "content": text}},
        {"timestamp": "2026-04-18T12:00:02Z", "message": {"role": "assistant", "content": "ok"}},
    ]


def test_parse_cache_hit_skips_reparse(tmp_path, monkeypatch):
    import api.models as models

    models.clear_claude_code_parse_cache()
    fixture = tmp_path / "claude" / "projects" / "p" / "s.jsonl"
    _write_jsonl(fixture, _rows())

    calls = {"n": 0}
    real = models._parse_claude_code_jsonl

    def _counting(path, **kw):
        calls["n"] += 1
        return real(path, **kw)

    monkeypatch.setattr(models, "_parse_claude_code_jsonl", _counting)

    first = models._parse_claude_code_jsonl_cached(fixture)
    second = models._parse_claude_code_jsonl_cached(fixture)

    # Second call is served from cache: underlying parser ran exactly once.
    assert calls["n"] == 1
    assert first == second
    assert first[0][0]["content"] == "hello"


def test_parse_cache_invalidates_on_content_change(tmp_path, monkeypatch):
    import api.models as models

    models.clear_claude_code_parse_cache()
    fixture = tmp_path / "claude" / "projects" / "p" / "s.jsonl"
    _write_jsonl(fixture, _rows("first"))

    calls = {"n": 0}
    real = models._parse_claude_code_jsonl

    def _counting(path, **kw):
        calls["n"] += 1
        return real(path, **kw)

    monkeypatch.setattr(models, "_parse_claude_code_jsonl", _counting)

    first = models._parse_claude_code_jsonl_cached(fixture)
    assert first[0][0]["content"] == "first"

    # Rewrite with different content + a guaranteed-distinct mtime/size so the
    # stat signature changes and the cache must miss.
    time.sleep(0.01)
    _write_jsonl(fixture, _rows("second-edition-longer"))
    import os
    st = fixture.stat()
    os.utime(fixture, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    second = models._parse_claude_code_jsonl_cached(fixture)

    assert calls["n"] == 2  # re-parsed after the edit
    assert second[0][0]["content"] == "second-edition-longer"


def test_parse_cache_returns_independent_message_lists(tmp_path):
    """A caller mutating the returned list must not corrupt the cached entry."""
    import api.models as models

    models.clear_claude_code_parse_cache()
    fixture = tmp_path / "claude" / "projects" / "p" / "s.jsonl"
    _write_jsonl(fixture, _rows())

    first_msgs, *_ = models._parse_claude_code_jsonl_cached(fixture)
    first_msgs.append({"role": "user", "content": "injected"})

    second_msgs, *_ = models._parse_claude_code_jsonl_cached(fixture)
    assert not any(m.get("content") == "injected" for m in second_msgs)


def test_parse_cache_is_bounded(tmp_path, monkeypatch):
    import api.models as models

    models.clear_claude_code_parse_cache()
    monkeypatch.setattr(models, "_CLAUDE_CODE_PARSE_CACHE_MAX", 5)

    for i in range(12):
        f = tmp_path / "claude" / "projects" / "p" / f"s{i}.jsonl"
        _write_jsonl(f, _rows(f"msg-{i}"))
        models._parse_claude_code_jsonl_cached(f)

    assert len(models._CLAUDE_CODE_PARSE_CACHE) <= 5


def test_parse_cache_handles_missing_file(tmp_path):
    import api.models as models

    models.clear_claude_code_parse_cache()
    missing = tmp_path / "nope.jsonl"
    # Must not raise; matches the empty-tuple contract of the uncached parser.
    # The trailing dict carries per-file metadata (real cwd, git branch) that
    # the sidebar uses instead of a fabricated shared workspace.
    assert models._parse_claude_code_jsonl_cached(missing) == ([], None, None, None, {})


def test_get_claude_code_sessions_is_retired_and_never_scans(tmp_path, monkeypatch):
    """External Claude Code scanning is retired; Jaeger is the sole runtime.

    This test used to assert the end-to-end warm-cache path (cold build parses
    each transcript once, warm build re-parses none). ``get_claude_code_sessions``
    now returns ``[]`` without touching the filesystem, so that assertion pinned
    behavior the product deliberately removed and failed with ``0 == 3``.

    The retirement is the contract worth pinning: present-but-ignored transcripts
    must yield no sessions AND no parse calls, so an accidental re-introduction of
    external scanning is caught here rather than surfacing as foreign sessions in
    the sidebar. The low-level ``_parse_claude_code_jsonl_cached`` memoization is
    still live and is covered by the other tests in this file.
    """
    import api.models as models

    models.clear_claude_code_parse_cache()
    projects_dir = tmp_path / "claude" / "projects"
    for i in range(3):
        _write_jsonl(projects_dir / f"proj{i}" / "s.jsonl", _rows(f"row-{i}"))

    calls = {"n": 0}
    real = models._parse_claude_code_jsonl

    def _counting(path, **kw):
        calls["n"] += 1
        return real(path, **kw)

    monkeypatch.setattr(models, "_parse_claude_code_jsonl", _counting)

    assert models.get_claude_code_sessions(projects_dir=projects_dir) == []
    assert calls["n"] == 0, "retired scanner must not parse transcripts at all"
    # Message reading is retired on the same contract.
    assert models.get_claude_code_session_messages("any-sid", projects_dir=projects_dir) == []
    assert calls["n"] == 0


# ``test_epoch_zero_timestamps_fall_back_to_mtime`` was removed here. It pinned
# the session-row builder's ``not first_ts and not last_ts`` mtime fallback for
# epoch-0 transcripts, but that builder lived inside ``get_claude_code_sessions``
# and was deleted when external Claude Code scanning was retired. The guard no
# longer exists anywhere in ``api/models.py``, so the test asserted a behavior the
# product intentionally removed (it failed with ``0 == 1``). It is dropped rather
# than relocated: there is no surviving code path that builds these rows, and
# re-adding one purely to satisfy a test would resurrect the retired scanner.


def test_parse_cache_dicts_are_read_only_contract(tmp_path):
    """Pin the load-bearing invariant: per-message dicts are SHARED across hits.

    The cache returns a shallow ``list(messages)`` copy, so the per-message dicts
    are shared between calls. Every production caller treats them as read-only;
    this test documents that contract by proving the sharing exists — a future
    caller that mutates a returned dict in place would corrupt the cache, and
    this test makes that sharing explicit so such a change is a conscious one.
    """
    import api.models as models

    models.clear_claude_code_parse_cache()
    fixture = tmp_path / "claude" / "projects" / "p" / "s.jsonl"
    _write_jsonl(fixture, _rows())

    first_msgs, *_ = models._parse_claude_code_jsonl_cached(fixture)
    second_msgs, *_ = models._parse_claude_code_jsonl_cached(fixture)
    # List wrappers are distinct copies (append isolation, covered above)...
    assert first_msgs is not second_msgs
    # ...but the dict objects are shared (the read-only contract). If a future
    # change deep-copies on read, update this assertion deliberately.
    assert first_msgs[0] is second_msgs[0]


def test_parse_cache_invalidates_on_same_size_mtime_ctime_edit(tmp_path, monkeypatch):
    """A same-size, same-mtime in-place edit still misses the cache via ctime_ns."""
    import os
    import api.models as models

    models.clear_claude_code_parse_cache()
    fixture = tmp_path / "claude" / "projects" / "p" / "s.jsonl"
    _write_jsonl(fixture, _rows("aaaaa"))

    calls = {"n": 0}
    real = models._parse_claude_code_jsonl

    def _counting(path, **kw):
        calls["n"] += 1
        return real(path, **kw)

    monkeypatch.setattr(models, "_parse_claude_code_jsonl", _counting)

    first = models._parse_claude_code_jsonl_cached(fixture)
    assert first[0][0]["content"] == "aaaaa"
    st = fixture.stat()

    # Rewrite with same byte length and force the SAME mtime back; the os.utime
    # call still stamps ctime with the current wall clock, so a real in-place
    # edit moves ctime even when size+mtime are unchanged. Sleep so that ctime is
    # measurably distinct from the original mtime_ns we restore.
    time.sleep(0.02)
    _write_jsonl(fixture, _rows("bbbbb"))
    os.utime(fixture, ns=(st.st_atime_ns, st.st_mtime_ns))
    st2 = fixture.stat()
    assert st2.st_size == st.st_size
    assert st2.st_mtime_ns == st.st_mtime_ns
    assert st2.st_ctime_ns != st.st_ctime_ns  # only ctime moved (the edit signal)

    second = models._parse_claude_code_jsonl_cached(fixture)
    assert calls["n"] == 2  # re-parsed despite identical size+mtime (ctime caught it)
    assert second[0][0]["content"] == "bbbbb"
