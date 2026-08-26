import plistlib
from pathlib import Path

import pytest

from api import safari_bookmarks as sb


def _leaf(title, url):
    return {
        "WebBookmarkType": "WebBookmarkTypeLeaf",
        "URLString": url,
        "URIDictionary": {"title": title},
        "WebBookmarkUUID": title,
    }


def _write(path: Path):
    data = {
        "Title": "Bookmarks", "WebBookmarkType": "WebBookmarkTypeList",
        "Children": [
            {"Title": "BookmarksBar", "WebBookmarkType": "WebBookmarkTypeList", "Children": [
                _leaf("Keep", "HTTPS://Example.com/path/#fragment"),
                _leaf("Duplicate", "https://example.com/path"),
                _leaf("Other", "https://other.example/a"),
                {"Title": "Empty", "WebBookmarkType": "WebBookmarkTypeList", "Children": []},
            ]},
            {"Title": "BookmarksMenu", "WebBookmarkType": "WebBookmarkTypeList", "Children": [
                _leaf("Intentional other-folder copy", "https://example.com/path"),
            ]},
            {"Title": "com.apple.ReadingList", "WebBookmarkType": "WebBookmarkTypeList", "Children": [
                _leaf("Reading one", "https://read.example/"),
                _leaf("Reading duplicate", "https://read.example/"),
            ]},
        ],
    }
    with path.open("wb") as handle:
        plistlib.dump(data, handle, fmt=plistlib.FMT_BINARY)


@pytest.fixture
def bookmark_env(tmp_path, monkeypatch):
    source = tmp_path / "Bookmarks.plist"
    _write(source)
    monkeypatch.setenv("ARES_SAFARI_BOOKMARKS_PATH", str(source))
    monkeypatch.setenv("ARES_SAFARI_BOOKMARKS_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(sb, "_safari_running", lambda: False)
    return source


def test_audit_proposes_only_same_folder_non_reading_list_duplicates(bookmark_env):
    proposal = sb.create_proposal()
    assert proposal["bookmark_count"] == 6
    assert proposal["duplicate_group_count"] == 1
    assert proposal["duplicate_removal_count"] == 1
    assert proposal["removals"][0]["title"] == "Duplicate"
    assert proposal["empty_folder_count"] == 1
    summary = sb.public_summary(proposal)
    rendered = str(summary)
    assert "https://" not in rendered
    assert "Duplicate" not in rendered


def test_apply_requires_exact_token_and_unchanged_source(bookmark_env):
    proposal = sb.create_proposal()
    with pytest.raises(sb.SafariBookmarkError, match="token"):
        sb.apply_proposal(proposal["proposal_id"], "wrong-token-value")
    bookmark_env.write_bytes(bookmark_env.read_bytes() + b"changed")
    with pytest.raises(sb.SafariBookmarkError, match="changed after"):
        sb.apply_proposal(proposal["proposal_id"], proposal["approval_token"])


def test_apply_creates_verified_backup_and_rollback_restores_source(bookmark_env):
    before = bookmark_env.read_bytes()
    proposal = sb.create_proposal()
    result = sb.apply_proposal(proposal["proposal_id"], proposal["approval_token"])
    assert result["status"] == "applied"
    assert result["duplicate_removal_count"] == 1
    assert Path(result["backup_path"]).read_bytes() == before
    with bookmark_env.open("rb") as handle:
        after = plistlib.load(handle)
    assert len(after["Children"][0]["Children"]) == 3
    with pytest.raises(sb.SafariBookmarkError, match="token"):
        sb.rollback_proposal(proposal["proposal_id"], "wrong-token-value")
    rolled_back = sb.rollback_proposal(proposal["proposal_id"], proposal["approval_token"])
    assert rolled_back["status"] == "rolled_back"
    assert bookmark_env.read_bytes() == before


def test_apply_refuses_while_safari_is_running(bookmark_env, monkeypatch):
    proposal = sb.create_proposal()
    monkeypatch.setattr(sb, "_safari_running", lambda: True)
    with pytest.raises(sb.SafariBookmarkError, match="Quit Safari"):
        sb.apply_proposal(proposal["proposal_id"], proposal["approval_token"])


def test_api_audit_omits_private_details(bookmark_env):
    from fastapi_app.routers.safari_bookmarks import audit_bookmarks

    body = audit_bookmarks(None)
    assert body["approval_required"] is True
    rendered = str(body)
    assert "https://" not in rendered
    assert "approval_token" not in rendered
