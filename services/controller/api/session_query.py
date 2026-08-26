"""Transport-neutral session search and export operations."""

from __future__ import annotations

import base64
import json
import re
from typing import Any


def session_search_message_text(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, list):
        return " ".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content or "")


def session_search_preview(text: Any, query: Any, max_len: int = 124) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    term = re.sub(r"\s+", " ", str(query or "")).strip()
    if not normalized or not term:
        return ""
    index = normalized.lower().find(term.lower())
    if index < 0:
        return ""
    max_len = max(32, int(max_len or 124))
    if len(normalized) <= max_len:
        return normalized
    context = max(12, (max_len - len(term)) // 2)
    start = max(0, index - context)
    end = min(len(normalized), index + len(term) + context)
    if start > 0:
        while start < index and normalized[start] != " ":
            start += 1
        if start >= index:
            start = max(0, index - context)
    if end < len(normalized):
        while end > index + len(term) and normalized[end - 1] != " ":
            end -= 1
        if end <= index + len(term):
            end = min(len(normalized), index + len(term) + context)
    excerpt = normalized[start:end].strip()
    return ("..." if start else "") + excerpt + ("..." if end < len(normalized) else "")


def search_sessions(
    query: str,
    *,
    content_search: bool = True,
    depth: int = 5,
    all_profiles: bool = False,
    lineage: bool = True,
) -> dict[str, Any]:
    from api.helpers import _redact_text
    from api.models import all_sessions, get_session
    from api.profiles import _profiles_match, get_active_profile_name

    term = str(query or "").lower().strip()
    active_profile = get_active_profile_name()
    sessions = all_sessions()
    if not all_profiles:
        sessions = [row for row in sessions if _profiles_match(row.get("profile"), active_profile)]
    depth = max(0, int(depth))
    if not term:
        safe = []
        for row in sessions:
            item = dict(row)
            if isinstance(item.get("title"), str):
                item["title"] = _redact_text(item["title"])
            safe.append(item)
        return {"sessions": safe, "all_profiles": all_profiles, "active_profile": active_profile}
    from api.backend_catalog import JAEGER_BACKEND_ID
    from api.session_contract import (
        backend_for_session,
        require_operation,
        runtime_owns_transcript,
        runtime_query,
    )

    jaeger_rows = [
        row
        for row in sessions
        if backend_for_session(row) == JAEGER_BACKEND_ID and runtime_owns_transcript(row)
    ]
    jaeger_matches: set[str] = set()
    if content_search and jaeger_rows:
        require_operation("search", backend=JAEGER_BACKEND_ID)
        jaeger_matches = {
            str(item.get("id"))
            for item in (runtime_query("search", query=term, limit=10_000) or [])
            if isinstance(item, dict) and item.get("id")
        }
    results = []
    for row in sessions:
        if term in str(row.get("title") or "").lower():
            item = dict(row, match_type="title")
        elif (
            content_search
            and backend_for_session(row) == JAEGER_BACKEND_ID
            and runtime_owns_transcript(row)
        ):
            session_id = str(row.get("session_id") or "")
            if session_id not in jaeger_matches:
                continue
            require_operation("load", backend=JAEGER_BACKEND_ID)
            messages = runtime_query("load", session_id=session_id)
            messages = messages[:depth] if depth else messages
            match = next(
                (
                    str(message.get("text") or "")
                    for message in messages
                    if isinstance(message, dict)
                    and term in str(message.get("text") or "").lower()
                ),
                None,
            )
            item = dict(row, match_type="content")
            preview = session_search_preview(match, term)
            if preview:
                item["match_preview"] = _redact_text(preview)
        elif content_search:
            try:
                messages = get_session(row["session_id"]).messages
                messages = messages[:depth] if depth else messages
                match = next(
                    (session_search_message_text(message) for message in messages if term in session_search_message_text(message).lower()),
                    None,
                )
            except Exception:
                match = None
            if match is None:
                continue
            item = dict(row, match_type="content")
            preview = session_search_preview(match, term)
            if preview:
                item["match_preview"] = _redact_text(preview)
        else:
            continue
        if isinstance(item.get("title"), str):
            item["title"] = _redact_text(item["title"])
        results.append(item)
    if lineage and results:
        by_id = {str(row.get("session_id") or row.get("id") or ""): row for row in sessions}

        def lineage_root(row: dict[str, Any]) -> str:
            current = str(row.get("_lineage_root_id") or row.get("session_id") or row.get("id") or "")
            if row.get("_lineage_root_id"):
                return current
            seen = {current}
            parent = row.get("parent_session_id")
            while parent and str(parent) not in seen:
                current = str(parent)
                seen.add(current)
                parent = by_id.get(current, {}).get("parent_session_id")
            return current

        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            grouped.setdefault(lineage_root(item), []).append(item)
        collapsed = []
        for root_id, matches in grouped.items():
            tip_id = next((str(item.get("_lineage_tip_id")) for item in matches if item.get("_lineage_tip_id")), "")
            match_ids = [str(item.get("session_id") or item.get("id")) for item in matches]
            member_rows = [row for sid, row in by_id.items() if sid and lineage_root(row) == root_id]
            member_ids = [str(row.get("session_id") or row.get("id")) for row in member_rows]
            representative = by_id.get(tip_id) or max(
                member_rows or matches,
                key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            )
            merged = dict(representative)
            merged.update({
                "match_type": matches[0].get("match_type"),
                "match_preview": matches[0].get("match_preview"),
                "lineage_root_id": root_id,
                "lineage_tip_id": tip_id or str(representative.get("session_id") or representative.get("id") or ""),
                "lineage_match_session_ids": match_ids,
                "lineage_session_ids": member_ids,
                "lineage_size": len(member_ids),
            })
            collapsed.append(merged)
        results = collapsed

    delegated_matches = []
    if lineage:
        try:
            from api.delegation_tasks import list_tasks
            for task in list_tasks():
                haystack = " ".join(str(task.get(key) or "") for key in ("prompt", "result", "error"))
                if term and term not in haystack.lower():
                    continue
                safe_task = {key: task.get(key) for key in (
                    "id", "status", "backend", "parent_task_id", "root_task_id",
                    "parent_session_id", "relation", "created_at", "updated_at",
                )}
                safe_task["match_preview"] = _redact_text(session_search_preview(haystack, term)) if term else ""
                delegated_matches.append(safe_task)
        except Exception:
            delegated_matches = []
    return {
        "sessions": results,
        "query": term,
        "count": len(results),
        "lineage_aware": lineage,
        "delegated_tasks": delegated_matches,
        "all_profiles": all_profiles,
        "active_profile": active_profile,
    }


def export_session(
    session_id: str,
    *,
    profile: str | None,
    format: str = "json",
    theme: str = "dark",
    palette: str = "",
) -> tuple[str, str, str]:
    from api.helpers import redact_session_data
    from api.models import get_session
    from api.profiles import _profiles_match, get_active_profile_name

    try:
        session = get_session(session_id)
    except KeyError as exc:
        raise FileNotFoundError("Session not found") from exc
    active_profile = profile or get_active_profile_name()
    if not _profiles_match(getattr(session, "profile", None), active_profile):
        raise FileNotFoundError("Session not found")
    from api.session_projection import project_session_detail

    safe = redact_session_data(project_session_detail(session, load_messages=True))
    if format.lower() != "html":
        return json.dumps(safe, ensure_ascii=False, indent=2), "application/json; charset=utf-8", "json"
    from api.session_export_html import render_session_html

    custom_palette = None
    if palette:
        try:
            decoded = base64.b64decode(palette, validate=False).decode("utf-8")
            candidate = json.loads(decoded)
            if isinstance(candidate, dict) and len(candidate) <= 64:
                custom_palette = candidate
        except Exception:
            pass
    return render_session_html(safe, theme=theme.lower(), palette=custom_palette), "text/html; charset=utf-8", "html"


_session_search_message_text = session_search_message_text
_session_search_preview = session_search_preview
