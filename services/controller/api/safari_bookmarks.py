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
import re
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


def _structural_sha256(path: Path) -> str:
    """Hash user-visible hierarchy while ignoring Safari-owned container UUID churn."""
    def project(node: dict[str, Any]) -> dict[str, Any]:
        children = node.get("Children")
        value = {key: node.get(key) for key in (
            "WebBookmarkType", "WebBookmarkIdentifier", "Title", "URLString",
        ) if node.get(key) is not None}
        if node.get("URLString") is not None and node.get("WebBookmarkUUID") is not None:
            value["WebBookmarkUUID"] = node["WebBookmarkUUID"]
        uri = node.get("URIDictionary")
        if isinstance(uri, dict) and uri.get("title") is not None:
            value["uri_title"] = uri["title"]
        if isinstance(children, list):
            value["Children"] = [project(child) for child in children if isinstance(child, dict)]
        return value

    encoded = json.dumps(
        project(_load(path)), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def create_recovery_proposal(restore_from: Path, path: Path | None = None) -> dict[str, Any]:
    """Prepare an approval-gated exact restore without changing either file."""
    source = (path or bookmark_path()).expanduser().resolve()
    backup = restore_from.expanduser().resolve()
    if source == backup:
        raise SafariBookmarkError("Recovery source must differ from the live bookmark file")
    current_data = _load(source)
    restore_data = _load(backup)
    current_bookmarks, current_empty, current_folders = _inventory(current_data)
    restore_bookmarks, restore_empty, restore_folders = _inventory(restore_data)
    proposal_id = secrets.token_hex(8)
    proposal = {
        "schema": "ares-safari-bookmark-recovery/v1",
        "operation": "exact_recovery",
        "proposal_id": proposal_id,
        "approval_token": secrets.token_urlsafe(12),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source),
        "source_sha256": _sha256(source),
        "bookmark_count": len(current_bookmarks),
        "folder_count": current_folders,
        "empty_folder_count": len(current_empty),
        "restore_from_path": str(backup),
        "restore_from_sha256": _sha256(backup),
        "restore_structural_sha256": _structural_sha256(backup),
        "restore_bookmark_count": len(restore_bookmarks),
        "restore_folder_count": restore_folders,
        "restore_empty_folder_count": len(restore_empty),
        "status": "awaiting_approval",
    }
    directory = state_root() / "proposals"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / f"{proposal_id}.json"
    target.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
    target.chmod(0o600)
    return proposal


def create_organization_proposal(path: Path | None = None) -> dict[str, Any]:
    """Plan moves for loose root/Favourites leaves into populated existing folders."""
    source = (path or bookmark_path()).expanduser().resolve()
    data = _load(source)
    bookmarks, empty_folders, folder_count = _inventory(data)
    folders: list[dict[str, Any]] = []
    loose: list[dict[str, Any]] = []

    def words(value: str) -> set[str]:
        return {word for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) > 2}

    def walk(node: dict[str, Any], node_path: list[int], labels: list[str]) -> None:
        children = node.get("Children")
        if not isinstance(children, list):
            return
        label = str(node.get("Title") or node.get("WebBookmarkIdentifier") or "Bookmarks")
        next_labels = labels + [label]
        is_system = label in {"com.apple.ReadingList", "History"}
        if labels and not is_system and label != "BookmarksBar":
            folders.append({"path": node_path, "labels": next_labels, "node": node, "items": []})
        for index, child in enumerate(children):
            if not isinstance(child, dict):
                continue
            child_path = node_path + [index]
            if child.get("URLString"):
                item = {
                    "path": child_path, "node": child, "url": str(child.get("URLString") or ""),
                    "canonical": _canonical_url(str(child.get("URLString") or "")),
                    "domain": str(urlsplit(str(child.get("URLString") or "")).hostname or "").lower(),
                    "text": f"{_title(child)} {child.get('URLString') or ''}",
                }
                if not is_system and (not labels or label == "BookmarksBar"):
                    loose.append(item)
            elif isinstance(child.get("Children"), list):
                walk(child, child_path, next_labels)

    walk(data, [], [])
    loose_paths = {tuple(item["path"]) for item in loose}
    for item in bookmarks:
        item_path = tuple(int(v) for v in item["path"])
        if item_path in loose_paths:
            continue
        for folder in folders:
            folder_path = tuple(folder["path"])
            if item_path[:-1] == folder_path:
                folder["items"].append(item)
                break

    menu = next((child for child in data.get("Children", []) if isinstance(child, dict) and child.get("Title") == "BookmarksMenu"), None)
    menu_path = next(([index] for index, child in enumerate(data.get("Children", [])) if child is menu), None)
    if menu is None or menu_path is None:
        raise SafariBookmarkError("Safari BookmarksMenu folder was not found")
    moves = []
    reason_counts: dict[str, int] = {"exact_url": 0, "domain": 0, "label": 0, "unsorted": 0}
    needs_unsorted = False
    for item in loose:
        best = None
        for folder in folders:
            exact = sum(1 for existing in folder["items"] if existing["canonical_url"] == item["canonical"])
            domain = sum(1 for existing in folder["items"] if existing["domain"] and existing["domain"] == item["domain"])
            overlap = len(words(item["text"]) & words(" ".join(folder["labels"])))
            score = exact * 10000 + domain * 100 + overlap
            candidate = (score, len(folder["path"]), folder)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        score, _depth, destination = best if best is not None else (0, 0, None)
        if destination is None or score <= 0:
            destination_path = None
            reason = "unsorted"
            needs_unsorted = True
        else:
            destination_path = destination["path"]
            reason = "exact_url" if score >= 10000 else "domain" if score >= 100 else "label"
        reason_counts[reason] += 1
        moves.append({"source_path": item["path"], "destination_path": destination_path, "reason": reason})
    proposal_id = secrets.token_hex(8)
    proposal = {
        "schema": "ares-safari-bookmark-organization/v1", "operation": "organize_loose_bookmarks",
        "proposal_id": proposal_id, "approval_token": secrets.token_urlsafe(12),
        "created_at": datetime.now(timezone.utc).isoformat(), "source_path": str(source),
        "source_sha256": _sha256(source), "source_structural_sha256": _structural_sha256(source),
        "bookmark_count": len(bookmarks), "folder_count": folder_count,
        "empty_folder_count": len(empty_folders), "move_count": len(moves),
        "reason_counts": reason_counts, "create_unsorted_folder": needs_unsorted,
        "bookmarks_menu_path": menu_path, "moves": moves, "status": "awaiting_approval",
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
        "schema", "operation", "proposal_id", "created_at", "bookmark_count", "folder_count",
        "duplicate_group_count", "duplicate_removal_count", "malformed_count",
        "empty_folder_count", "status", "backup_path", "applied_at", "rolled_back_at",
        "restore_bookmark_count", "restore_folder_count", "restore_empty_folder_count",
        "move_count", "reason_counts", "create_unsorted_folder",
    )}


def apply_recovery_proposal(proposal_id: str, approval_token: str) -> dict[str, Any]:
    """Restore an audited plist exactly, while preserving the damaged state for rollback."""
    proposal = load_proposal(proposal_id)
    if proposal.get("operation") != "exact_recovery":
        raise SafariBookmarkError("Proposal is not a bookmark recovery")
    if proposal.get("status") != "awaiting_approval":
        raise SafariBookmarkError(f"Proposal is not pending (status={proposal.get('status')})")
    if not secrets.compare_digest(str(proposal.get("approval_token") or ""), str(approval_token or "")):
        raise SafariBookmarkError("Explicit approval token did not match")
    source = Path(str(proposal["source_path"])).resolve()
    restore_from = Path(str(proposal["restore_from_path"])).resolve()
    if _sha256(source) != proposal.get("source_sha256"):
        raise SafariBookmarkError("Safari bookmarks changed after the recovery audit; create a new proposal")
    if not restore_from.is_file() or _sha256(restore_from) != proposal.get("restore_from_sha256"):
        raise SafariBookmarkError("The audited recovery source changed or is unavailable")
    if _requires_safari_quit(source):
        raise SafariBookmarkError("Quit Safari before applying bookmark recovery")
    backups = state_root() / "backups"
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    damaged_backup = backups / f"Bookmarks-before-recovery-{proposal_id}.plist"
    shutil.copy2(source, damaged_backup)
    if _sha256(damaged_backup) != proposal["source_sha256"]:
        raise SafariBookmarkError("Pre-recovery backup checksum verification failed")
    _atomic_restore(restore_from, source)
    restored, restored_empty, restored_folders = _inventory(_load(source))
    if (
        _sha256(source) != proposal["restore_from_sha256"]
        or len(restored) != int(proposal["restore_bookmark_count"])
        or restored_folders != int(proposal["restore_folder_count"])
        or len(restored_empty) != int(proposal["restore_empty_folder_count"])
    ):
        _atomic_restore(damaged_backup, source)
        raise SafariBookmarkError("Post-recovery verification failed; damaged-state backup was restored")
    proposal.update({
        "status": "applied",
        "backup_path": str(damaged_backup),
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "result_sha256": _sha256(source),
    })
    _save_proposal(proposal)
    return public_summary(proposal)


def apply_organization_proposal(proposal_id: str, approval_token: str) -> dict[str, Any]:
    proposal = load_proposal(proposal_id)
    if proposal.get("operation") != "organize_loose_bookmarks":
        raise SafariBookmarkError("Proposal is not a bookmark organization")
    if proposal.get("status") != "awaiting_approval":
        raise SafariBookmarkError(f"Proposal is not pending (status={proposal.get('status')})")
    if not secrets.compare_digest(str(proposal.get("approval_token") or ""), str(approval_token or "")):
        raise SafariBookmarkError("Explicit approval token did not match")
    source = Path(str(proposal["source_path"])).resolve()
    if _sha256(source) != proposal.get("source_sha256"):
        raise SafariBookmarkError("Safari bookmarks changed after the organization audit; create a new proposal")
    if _requires_safari_quit(source):
        raise SafariBookmarkError("Quit Safari before applying bookmark organization")
    data = _load(source)
    resolved = []
    for move in proposal.get("moves") or []:
        parent = _node_at(data, list(move["source_path"][:-1]))
        child = parent["Children"][int(move["source_path"][-1])]
        destination = _node_at(data, list(move["destination_path"])) if move.get("destination_path") is not None else None
        resolved.append((parent, int(move["source_path"][-1]), child, destination))
    unsorted = None
    if proposal.get("create_unsorted_folder"):
        menu = _node_at(data, list(proposal["bookmarks_menu_path"]))
        unsorted = {"Title": "Unsorted (ARES)", "WebBookmarkType": "WebBookmarkTypeList", "Children": []}
        menu["Children"].append(unsorted)
    by_parent: dict[int, tuple[dict[str, Any], list[int]]] = {}
    for parent, index, _child, _destination in resolved:
        entry = by_parent.setdefault(id(parent), (parent, []))
        entry[1].append(index)
    for parent, indexes in by_parent.values():
        for index in sorted(indexes, reverse=True):
            parent["Children"].pop(index)
    for _parent, _index, child, destination in resolved:
        (destination or unsorted)["Children"].append(child)
    backups = state_root() / "backups"
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backups / f"Bookmarks-before-organization-{proposal_id}.plist"
    shutil.copy2(source, backup)
    if _sha256(backup) != proposal["source_sha256"]:
        raise SafariBookmarkError("Pre-organization backup checksum verification failed")
    mode = source.stat().st_mode & 0o777
    fd, temporary_name = tempfile.mkstemp(prefix=".Bookmarks.ares-organize-", suffix=".plist", dir=source.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            plistlib.dump(data, handle, fmt=plistlib.FMT_BINARY, sort_keys=False)
            handle.flush(); os.fsync(handle.fileno())
        temporary = Path(temporary_name); temporary.chmod(mode); _load(temporary)
        os.replace(temporary, source)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    verified, verified_empty, verified_folders = _inventory(_load(source))
    if len(verified) != int(proposal["bookmark_count"]):
        _atomic_restore(backup, source)
        raise SafariBookmarkError("Post-organization bookmark count failed; backup was restored")
    proposal.update({
        "status": "applied", "backup_path": str(backup),
        "applied_at": datetime.now(timezone.utc).isoformat(), "result_sha256": _sha256(source),
        "result_structural_sha256": _structural_sha256(source),
        "result_folder_count": verified_folders, "result_empty_folder_count": len(verified_empty),
    })
    _save_proposal(proposal)
    return public_summary(proposal)


def _safari_running() -> bool:
    return subprocess.run(["pgrep", "-x", "Safari"], capture_output=True).returncode == 0


def _requires_safari_quit(source: Path) -> bool:
    """Safari can race only its real bookmark database, not test fixtures."""
    real_bookmarks = (Path.home() / "Library/Safari/Bookmarks.plist").resolve()
    return source.resolve() == real_bookmarks and _safari_running()


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
    if _requires_safari_quit(source):
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
    source = Path(str(proposal["source_path"])).resolve()
    if _requires_safari_quit(source):
        raise SafariBookmarkError("Quit Safari before rolling back bookmark changes")
    backup = Path(str(proposal.get("backup_path") or "")).resolve()
    if not backup.is_file() or _sha256(backup) != proposal.get("source_sha256"):
        raise SafariBookmarkError("Verified backup is unavailable")
    _atomic_restore(backup, source)
    _load(source)
    proposal.update({"status": "rolled_back", "rolled_back_at": datetime.now(timezone.utc).isoformat()})
    _save_proposal(proposal)
    return public_summary(proposal)


def verify_proposal(proposal_id: str) -> dict[str, Any]:
    """Return aggregate post-operation evidence without private bookmark data."""
    proposal = load_proposal(proposal_id)
    source = Path(str(proposal["source_path"])).resolve()
    data = _load(source)
    bookmarks, _empty_folders, folders = _inventory(data)
    current_hash = _sha256(source)
    status = str(proposal.get("status") or "")
    expected_count = int(proposal.get("bookmark_count") or 0)
    if proposal.get("operation") == "exact_recovery" and status == "applied":
        expected_count = int(proposal.get("restore_bookmark_count") or 0)
    elif status == "applied":
        expected_count -= len(proposal.get("removals") or [])
    elif status == "rolled_back":
        expected_count = int(proposal.get("bookmark_count") or 0)
    backup_value = str(proposal.get("backup_path") or "")
    backup = Path(backup_value).resolve() if backup_value else None
    backup_valid = bool(
        backup is not None
        and backup.is_file()
        and _sha256(backup) == str(proposal.get("source_sha256") or "")
    )
    result_hash_matches = (
        current_hash == str(proposal.get("result_sha256") or "")
        if status == "applied" else None
    )
    expected_structure = str(proposal.get("restore_structural_sha256") or proposal.get("result_structural_sha256") or "")
    if not expected_structure and proposal.get("operation") == "exact_recovery":
        restore_value = str(proposal.get("restore_from_path") or "")
        restore_source = Path(restore_value).resolve() if restore_value else None
        if restore_source is not None and restore_source.is_file():
            expected_structure = _structural_sha256(restore_source)
    structural_hash = _structural_sha256(source)
    return {
        "proposal": public_summary(proposal),
        "verification": {
            "plist_valid": True,
            "bookmark_count": len(bookmarks),
            "expected_bookmark_count": expected_count,
            "bookmark_count_matches": len(bookmarks) == expected_count,
            "folder_count": folders,
            "current_sha256": current_hash,
            "result_sha256_matches": result_hash_matches,
            "structural_sha256": structural_hash,
            "structural_sha256_matches": (
                structural_hash == expected_structure if expected_structure else None
            ),
            "backup_valid": backup_valid,
        },
        "privacy": "aggregate only; no bookmark titles, URLs, or approval token",
    }


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
    "SafariBookmarkError", "apply_organization_proposal", "apply_proposal", "apply_recovery_proposal",
    "bookmark_path", "create_organization_proposal", "create_proposal", "create_recovery_proposal",
    "load_proposal", "public_summary", "rollback_proposal", "state_root",
    "verify_proposal",
]
