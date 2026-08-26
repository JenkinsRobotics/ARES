"""Local-only Safari bookmark audit and approval-gated mutation service.

Raw titles and URLs never leave this module unless a local CLI explicitly asks
for proposal details. Agent/API summaries contain counts and opaque item IDs.
"""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class SafariBookmarkError(RuntimeError):
    pass


def bookmark_path() -> Path:
    return Path(os.environ.get("ARES_SAFARI_BOOKMARKS_PATH") or Path.home() / "Library/Safari/Bookmarks.plist")


def state_root() -> Path:
    return Path(os.environ.get("ARES_SAFARI_BOOKMARKS_STATE") or Path.home() / ".ares/safari_bookmarks")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            value = plistlib.load(handle)
    except PermissionError as exc:
        raise SafariBookmarkError(f"Safari bookmark file is not readable: {exc}") from exc
    except (OSError, plistlib.InvalidFileException) as exc:
        raise SafariBookmarkError(f"Safari bookmark file is invalid or unavailable: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("Children"), list):
        raise SafariBookmarkError("Safari bookmark file has an unsupported structure")
    return value


def _canonical_url(raw: str) -> str:
    value = raw.strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return value
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        return value
    netloc = host
    if port and not ((parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def _title(node: dict[str, Any]) -> str:
    uri = node.get("URIDictionary") if isinstance(node.get("URIDictionary"), dict) else {}
    return str(uri.get("title") or node.get("Title") or "Untitled")


def _inventory(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    bookmarks: list[dict[str, Any]] = []
    empty_folders: list[dict[str, Any]] = []
    folder_count = 0

    def walk(node: dict[str, Any], path: list[int], labels: list[str], mutable: bool) -> None:
        nonlocal folder_count
        children = node.get("Children")
        if isinstance(children, list):
            folder_count += 1
            identifier = str(node.get("Title") or node.get("WebBookmarkIdentifier") or "Bookmarks")
            next_labels = labels + [identifier]
            if mutable and not children:
                empty_folders.append({"path": path, "title": identifier, "folder": "/".join(next_labels)})
            for index, child in enumerate(children):
                if not isinstance(child, dict):
                    continue
                child_identifier = str(child.get("Title") or child.get("WebBookmarkIdentifier") or "")
                child_mutable = mutable and child_identifier != "com.apple.ReadingList" and child.get("WebBookmarkType") != "WebBookmarkTypeProxy"
                walk(child, path + [index], next_labels, child_mutable)
            return
        url = str(node.get("URLString") or "").strip()
        if not url:
            return
        try:
            parsed = urlsplit(url)
            domain = (parsed.hostname or "").lower()
        except ValueError:
            domain = ""
        bookmarks.append({
            "path": path,
            "title": _title(node),
            "url": url,
            "canonical_url": _canonical_url(url),
            "domain": domain,
            "folder": "/".join(labels),
            "mutable": mutable,
        })

    walk(data, [], [], True)
    return bookmarks, empty_folders, folder_count


def create_proposal(path: Path | None = None) -> dict[str, Any]:
    source = (path or bookmark_path()).expanduser().resolve()
    data = _load(source)
    bookmarks, empty_folders, folder_count = _inventory(data)
    by_url: dict[str, list[dict[str, Any]]] = {}
    malformed = []
    for item in bookmarks:
        try:
            parsed = urlsplit(item["url"])
            is_web = parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
        except ValueError:
            is_web = False
        if not is_web:
            malformed.append(item)
        if item["mutable"]:
            # Repeated placement in different folders may be intentional. Only
            # propose automatic removal for the same URL in the same folder.
            by_url.setdefault(f"{item['folder']}\0{item['canonical_url']}", []).append(item)
    duplicate_groups = [rows for rows in by_url.values() if len(rows) > 1]
    removals = [item for rows in duplicate_groups for item in rows[1:]]
    proposal_id = secrets.token_hex(8)
    approval_token = secrets.token_urlsafe(12)
    created_at = datetime.now(timezone.utc).isoformat()
    proposal = {
        "schema": "ares-safari-bookmark-proposal/v1",
        "proposal_id": proposal_id,
        "approval_token": approval_token,
        "created_at": created_at,
        "source_path": str(source),
        "source_sha256": _sha256(source),
        "bookmark_count": len(bookmarks),
        "folder_count": folder_count,
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_removal_count": len(removals),
        "malformed_count": len(malformed),
        "empty_folder_count": len(empty_folders),
        "duplicate_groups": duplicate_groups,
        "removals": removals,
        "malformed": malformed,
        "empty_folders": empty_folders,
        "status": "awaiting_approval",
    }
    directory = state_root() / "proposals"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / f"{proposal_id}.json"
    target.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
    target.chmod(0o600)
    return proposal


def load_proposal(proposal_id: str) -> dict[str, Any]:
    if not proposal_id or any(ch not in "0123456789abcdef" for ch in proposal_id):
        raise SafariBookmarkError("Invalid proposal id")
    path = state_root() / "proposals" / f"{proposal_id}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafariBookmarkError("Bookmark proposal was not found or is unreadable") from exc
    if not isinstance(value, dict) or value.get("proposal_id") != proposal_id:
        raise SafariBookmarkError("Bookmark proposal is invalid")
    return value


def public_summary(proposal: dict[str, Any]) -> dict[str, Any]:
    return {key: proposal.get(key) for key in (
        "schema", "proposal_id", "created_at", "bookmark_count", "folder_count",
        "duplicate_group_count", "duplicate_removal_count", "malformed_count",
        "empty_folder_count", "status", "backup_path", "applied_at", "rolled_back_at",
    )}


def _safari_running() -> bool:
    return subprocess.run(["pgrep", "-x", "Safari"], capture_output=True).returncode == 0


def _node_at(data: dict[str, Any], parent_path: list[int]) -> dict[str, Any]:
    node = data
    for index in parent_path:
        children = node.get("Children")
        if not isinstance(children, list) or index < 0 or index >= len(children):
            raise SafariBookmarkError("Proposal path no longer matches the bookmark file")
        child = children[index]
        if not isinstance(child, dict):
            raise SafariBookmarkError("Proposal path points to an unsupported bookmark node")
        node = child
    return node


def apply_proposal(proposal_id: str, approval_token: str) -> dict[str, Any]:
    proposal = load_proposal(proposal_id)
    if proposal.get("status") != "awaiting_approval":
        raise SafariBookmarkError(f"Proposal is not pending (status={proposal.get('status')})")
    if not secrets.compare_digest(str(proposal.get("approval_token") or ""), str(approval_token or "")):
        raise SafariBookmarkError("Explicit approval token did not match")
    source = Path(str(proposal["source_path"])).resolve()
    if _sha256(source) != proposal.get("source_sha256"):
        raise SafariBookmarkError("Safari bookmarks changed after the audit; create a new proposal")
    if _safari_running():
        raise SafariBookmarkError("Quit Safari before applying bookmark changes")
    data = _load(source)
    removals = proposal.get("removals") if isinstance(proposal.get("removals"), list) else []
    if not removals:
        raise SafariBookmarkError("Proposal contains no automatic duplicate removals")
    grouped: dict[tuple[int, ...], list[int]] = {}
    for item in removals:
        path = item.get("path") if isinstance(item, dict) else None
        if not isinstance(path, list) or not path:
            raise SafariBookmarkError("Proposal contains an invalid removal path")
        grouped.setdefault(tuple(int(v) for v in path[:-1]), []).append(int(path[-1]))
    for parent_path, indexes in grouped.items():
        parent = _node_at(data, list(parent_path))
        children = parent.get("Children")
        if not isinstance(children, list):
            raise SafariBookmarkError("Proposal removal parent is not a folder")
        for index in sorted(set(indexes), reverse=True):
            if index < 0 or index >= len(children):
                raise SafariBookmarkError("Proposal removal index no longer exists")
            children.pop(index)
    backups = state_root() / "backups"
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backups / f"Bookmarks-{proposal_id}.plist"
    shutil.copy2(source, backup)
    if _sha256(backup) != proposal["source_sha256"]:
        raise SafariBookmarkError("Backup checksum verification failed")
    mode = source.stat().st_mode & 0o777
    fd, temporary_name = tempfile.mkstemp(prefix=".Bookmarks.ares-", suffix=".plist", dir=source.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            plistlib.dump(data, handle, fmt=plistlib.FMT_BINARY, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary = Path(temporary_name)
        temporary.chmod(mode)
        _load(temporary)
        os.replace(temporary, source)
    finally:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass
    verified, _, _ = _inventory(_load(source))
    expected_count = int(proposal["bookmark_count"]) - len(removals)
    if len(verified) != expected_count:
        _atomic_restore(backup, source)
        raise SafariBookmarkError("Post-write count verification failed; backup was restored")
    proposal.update({
        "status": "applied", "backup_path": str(backup),
        "applied_at": datetime.now(timezone.utc).isoformat(), "result_sha256": _sha256(source),
    })
    _save_proposal(proposal)
    return public_summary(proposal)


def rollback_proposal(proposal_id: str, approval_token: str) -> dict[str, Any]:
    proposal = load_proposal(proposal_id)
    if proposal.get("status") != "applied":
        raise SafariBookmarkError("Only an applied proposal can be rolled back")
    if not secrets.compare_digest(str(proposal.get("approval_token") or ""), str(approval_token or "")):
        raise SafariBookmarkError("Explicit approval token did not match")
    if _safari_running():
        raise SafariBookmarkError("Quit Safari before rolling back bookmark changes")
    source = Path(str(proposal["source_path"])).resolve()
    backup = Path(str(proposal.get("backup_path") or "")).resolve()
    if not backup.is_file() or _sha256(backup) != proposal.get("source_sha256"):
        raise SafariBookmarkError("Verified backup is unavailable")
    _atomic_restore(backup, source)
    _load(source)
    proposal.update({"status": "rolled_back", "rolled_back_at": datetime.now(timezone.utc).isoformat()})
    _save_proposal(proposal)
    return public_summary(proposal)


def _atomic_restore(backup: Path, source: Path) -> None:
    mode = source.stat().st_mode & 0o777 if source.exists() else backup.stat().st_mode & 0o777
    fd, temporary_name = tempfile.mkstemp(prefix=".Bookmarks.ares-restore-", suffix=".plist", dir=source.parent)
    try:
        with os.fdopen(fd, "wb") as target, backup.open("rb") as source_handle:
            shutil.copyfileobj(source_handle, target)
            target.flush()
            os.fsync(target.fileno())
        temporary = Path(temporary_name)
        temporary.chmod(mode)
        _load(temporary)
        os.replace(temporary, source)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _save_proposal(proposal: dict[str, Any]) -> None:
    target = state_root() / "proposals" / f"{proposal['proposal_id']}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, target)


__all__ = [
    "SafariBookmarkError", "apply_proposal", "bookmark_path", "create_proposal",
    "load_proposal", "public_summary", "rollback_proposal", "state_root",
]
