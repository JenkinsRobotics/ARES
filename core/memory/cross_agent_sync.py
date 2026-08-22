# ARES Cross-Agent Memory & Knowledge Synthesis Engine.
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .journal.paths import (
    ares_memory_dir,
    claude_projects_dir,
    codex_dir,
    hermes_db,
    journal_db,
    memory_imports_dir,
)

logger = logging.getLogger(__name__)

SKIP_TEXT = re.compile(
    r"^(yes|no|ok|y|n|thanks|thank\s+you|continue|proceed|go|done|exit|quit|help|clear)$"
    r"|^(\?|\!|\.|ls|cd|pwd|git\s+status|git\s+diff|npm\s+run|pytest|uv\s+run|echo)"
    r"|sk-[a-zA-Z0-9]{20,}"
    r"|ghp_[a-zA-Z0-9]{20,}",
    re.IGNORECASE,
)

INTERESTING_KEYWORDS = re.compile(
    r"(prefer|always|never|remember|note|decision|decided|architecture|refactor|rule|"
    r"convention|project|goal|blocker|todo|roadmap|doctrine|pattern|don't|do\s+not|must|"
    r"important|priority|focus|switch\s+to|use\s+|avoid|standard|policy)",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_memory_dirs() -> Tuple[Path, Path, Path]:
    mem_dir = ares_memory_dir()
    raw_dir = mem_dir / "raw"
    imports_dir = memory_imports_dir()
    raw_dir.mkdir(parents=True, exist_ok=True)
    imports_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir, raw_dir, imports_dir


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load %s: %s", path, e)
        return default if default is not None else {}


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def extract_claude_code(limit: int = 250) -> List[Dict[str, Any]]:
    proj_dir = claude_projects_dir()
    items: List[Dict[str, Any]] = []
    if not proj_dir.exists():
        return items

    jsonl_files = sorted(proj_dir.rglob("*.jsonl"), key=os.path.getmtime, reverse=True)
    for p in jsonl_files[:150]:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = ""
                    if row.get("type") == "user" or row.get("role") == "user":
                        content = row.get("content") or row.get("message") or ""
                        if isinstance(content, list):
                            text_parts = []
                            for c in content:
                                if isinstance(c, dict):
                                    if c.get("type") == "tool_result":
                                        continue
                                    if "text" in c:
                                        text_parts.append(c["text"])
                                elif isinstance(c, str):
                                    text_parts.append(c)
                            msg = " ".join(text_parts)
                        else:
                            msg = str(content)
                    elif "USER_INPUT" in str(row.get("type", "")):
                        msg = str(row.get("content", ""))

                    msg = msg.strip()
                    if len(msg) >= 15 and not SKIP_TEXT.search(msg):
                        items.append({
                            "source": "claude_code",
                            "text": msg[:2000],
                            "file": p.name,
                            "timestamp": os.path.getmtime(p),
                        })
                        if len(items) >= limit:
                            return items
        except Exception as e:
            logger.debug("Error reading Claude Code file %s: %s", p, e)
    return items


def extract_hermes(limit: int = 250) -> List[Dict[str, Any]]:
    db_path = hermes_db()
    items: List[Dict[str, Any]] = []
    if not db_path.exists():
        return items

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "messages" in tables:
            rows = cur.execute(
                """SELECT content, role, timestamp FROM messages
                   WHERE role IN ('user', 'system') AND length(content) >= 15
                   ORDER BY timestamp DESC LIMIT ?""",
                (limit * 2,),
            ).fetchall()
            for r in rows:
                txt = (r["content"] or "").strip()
                if txt and not SKIP_TEXT.search(txt):
                    items.append({
                        "source": "hermes",
                        "text": txt[:2000],
                        "timestamp": r["timestamp"] or time.time(),
                    })
                    if len(items) >= limit:
                        break
        conn.close()
    except Exception as e:
        logger.debug("Error extracting from Hermes: %s", e)
    return items


def extract_codex(limit: int = 150) -> List[Dict[str, Any]]:
    cdx_dir = codex_dir()
    items: List[Dict[str, Any]] = []
    if not cdx_dir.exists():
        return items

    for hf in [cdx_dir / "history.jsonl", cdx_dir / "sessions.jsonl"]:
        if hf.exists():
            try:
                with open(hf, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            txt = data.get("text") or data.get("content") or ""
                            if isinstance(txt, str) and len(txt.strip()) >= 15 and not SKIP_TEXT.search(txt):
                                items.append({
                                    "source": "codex",
                                    "text": txt.strip()[:2000],
                                    "timestamp": data.get("timestamp") or time.time(),
                                })
                                if len(items) >= limit:
                                    return items
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.debug("Error reading Codex file %s: %s", hf, e)
    return items


def extract_ares_journal(limit: int = 250) -> List[Dict[str, Any]]:
    j_db = journal_db()
    items: List[Dict[str, Any]] = []
    if not j_db.exists():
        return items

    try:
        conn = sqlite3.connect(str(j_db))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "messages" in tables:
            rows = cur.execute(
                """SELECT content, role, timestamp FROM messages
                   WHERE role = 'user' AND length(content) >= 15
                   ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            for r in rows:
                txt = (r["content"] or "").strip()
                if txt and not SKIP_TEXT.search(txt):
                    items.append({
                        "source": "ares_journal",
                        "text": txt[:2000],
                        "timestamp": r["timestamp"] or time.time(),
                    })
        conn.close()
    except Exception as e:
        logger.debug("Error extracting from ARES journal: %s", e)
    return items


def extract_export_drops(limit: int = 150) -> List[Dict[str, Any]]:
    imp_dir = memory_imports_dir()
    items: List[Dict[str, Any]] = []
    if not imp_dir.exists():
        return items

    for p in imp_dir.rglob("*"):
        if p.is_file() and p.name != "README.md" and not p.name.startswith("."):
            try:
                if p.suffix in (".json", ".jsonl"):
                    with open(p, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                        if p.suffix == ".jsonl":
                            for line in content.splitlines():
                                if line.strip():
                                    try:
                                        d = json.loads(line)
                                        txt = str(d.get("content") or d.get("text") or "")
                                        if len(txt) >= 15:
                                            items.append({"source": f"import_{p.parent.name}", "text": txt[:2000]})
                                    except Exception:
                                        pass
                        else:
                            d = json.loads(content)
                            if isinstance(d, list):
                                for elem in d[:50]:
                                    txt = str(elem.get("content") or elem.get("text") or "")
                                    if len(txt) >= 15:
                                        items.append({"source": f"import_{p.parent.name}", "text": txt[:2000]})
                elif p.suffix in (".md", ".txt"):
                    with open(p, "r", encoding="utf-8", errors="replace") as f:
                        for line in f.readlines():
                            p_clean = line.strip()
                            if len(p_clean) >= 20:
                                items.append({"source": f"import_{p.parent.name}", "text": p_clean[:2000]})
            except Exception as e:
                logger.debug("Error reading export file %s: %s", p, e)
            if len(items) >= limit:
                break
    return items


def filter_high_signal_items(items: List[Dict[str, Any]], max_keep: int = 150) -> List[Dict[str, Any]]:
    scored: List[Tuple[float, Dict[str, Any]]] = []
    seen_signatures: set = set()
    for item in items:
        text = item.get("text", "").strip()
        if len(text) < 15 or len(text) > 4000:
            continue
        if SKIP_TEXT.search(text):
            continue
        if "tool_use_id" in text or "tool_result" in text or text.startswith("{'role'"):
            continue
        sig = re.sub(r"\W+", " ", text.lower())[:80].strip()
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)
        score = 1.0
        matches = len(INTERESTING_KEYWORDS.findall(text))
        score += matches * 1.5
        if text.count(chr(10)) > 15 or "Traceback (most recent call last):" in text:
            score *= 0.3
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[:max_keep]]


def distill_facts_from_corpus(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    now_str = _now_iso()
    distilled: Dict[str, List[Dict[str, Any]]] = {
        "preferences": [],
        "decisions": [],
        "projects": [],
        "open_loops": [],
        "style_notes": [],
    }
    seen_facts: set = set()

    def add_fact(category: str, text: str, source: str, kind: str = "rule_distilled"):
        clean = re.sub(r"\s+", " ", text).strip()
        if len(clean) < 8 or len(clean) > 280:
            return
        sig = clean.lower()
        if sig in seen_facts:
            return
        seen_facts.add(sig)
        distilled[category].append({"text": clean, "source": source, "kind": kind, "at": now_str})

    for item in items:
        text = item.get("text", "")
        source = item.get("source", "unknown")
        clauses = [c.strip() for line in text.splitlines() for c in line.replace(";", ".").split(".") if c.strip()]
        for clause in clauses:
            clause = clause.strip().lstrip("-*•").strip()
            lower = clause.lower()
            if any(k in lower for k in ["prefer", "always use", "never use", "favor", "convention"]):
                add_fact("preferences", clause, source)
            elif any(k in lower for k in ["decided to", "decision:", "we chose", "architecture:", "doctrine:"]):
                add_fact("decisions", clause, source)
            elif any(k in lower for k in ["working on", "project:", "repo:", "building ", "component:"]):
                add_fact("projects", clause, source)
            elif any(k in lower for k in ["blocker:", "blocked by", "need to fix", "todo:", "open loop", "pending goal"]):
                add_fact("open_loops", clause, source)
            elif any(k in lower for k in ["communication style", "be concise", "direct tone", "no boilerplate", "style:"]):
                add_fact("style_notes", clause, source)

    if not distilled["preferences"]:
        add_fact("preferences", "Direct communication; verify changes before committing", "baseline")
        add_fact("preferences", "Local-first architectures with cloud fallback", "baseline")
    if not distilled["decisions"]:
        add_fact("decisions", "ARES = unified synthetic agent and control plane", "baseline")
    if not distilled["projects"]:
        add_fact("projects", "ARES — Autonomous Reasoning & Execution System", "baseline")
    return distilled


def generate_person_md(person: Dict[str, Any]) -> str:
    lines: List[str] = [
        "# Personal Profile & Cross-Agent Memory",
        f"*Last synthesized: {person.get('updated', _now_iso())}*",
        "",
        "> This profile is automatically compiled from conversation history across Claude Code, Hermes, Codex, and ARES.",
        "",
        "## 🛠️ Core Preferences",
    ]
    prefs = person.get("preferences", [])
    if prefs:
        for p in prefs[:15]:
            t = p.get("text", str(p)) if isinstance(p, dict) else str(p)
            lines.append(f"- {t}")
    else:
        lines.append("- *No specific preferences recorded yet.*")
    lines.extend(["", "## 🏛️ Architectural Decisions & Rulings"])
    decisions = person.get("decisions", [])
    if decisions:
        for d in decisions[:15]:
            t = d.get("text", str(d)) if isinstance(d, dict) else str(d)
            lines.append(f"- {t}")
    else:
        lines.append("- *No explicit architectural decisions recorded yet.*")
    lines.extend(["", "## 🚀 Active Projects"])
    projects = person.get("projects", [])
    if projects:
        for pr in projects[:15]:
            t = pr.get("text", str(pr)) if isinstance(pr, dict) else str(pr)
            lines.append(f"- {t}")
    else:
        lines.append("- *No active project definitions recorded yet.*")
    lines.extend(["", "## 🔄 Open Loops & In-Flight Work"])
    loops = person.get("open_loops", [])
    if loops:
        for ol in loops[:15]:
            t = ol.get("text", str(ol)) if isinstance(ol, dict) else str(ol)
            lines.append(f"- [ ] {t}")
    else:
        lines.append("- *No pending blockers or open loops recorded.*")
    lines.extend(["", "## 🎨 Style & Interaction Guidelines"])
    styles = person.get("style_notes", [])
    if styles:
        for st in styles[:10]:
            t = st.get("text", str(st)) if isinstance(st, dict) else str(st)
            lines.append(f"- {t}")
    else:
        lines.append("- Concise, technical, and direct responses.")
    stats = person.get("source_stats", {})
    if stats:
        lines.extend(["", "## 📊 Ingestion Source Breakdown"])
        for src, count in sorted(stats.items()):
            lines.append(f"- **{src}**: {count} items")
    lines.append("")
    return chr(10).join(lines)


def get_cross_agent_status() -> Dict[str, Any]:
    mem_dir, raw_dir, imp_dir = ensure_memory_dirs()
    state = load_json(mem_dir / "state.json", {})
    person = load_json(mem_dir / "person.json", {})
    claude_count = len(list(claude_projects_dir().rglob("*.jsonl"))) if claude_projects_dir().exists() else 0
    hermes_exists = hermes_db().exists()
    codex_exists = codex_dir().exists()
    imports_count = sum(1 for p in imp_dir.rglob("*") if p.is_file() and p.name != "README.md")
    return {
        "last_sync": state.get("last_ingest") or person.get("updated"),
        "available_sources": {
            "claude_code": {"available": claude_count > 0, "files_count": claude_count},
            "hermes": {"available": hermes_exists, "db_path": str(hermes_db())},
            "codex": {"available": codex_exists, "dir_path": str(codex_dir())},
            "ares_journal": {"available": journal_db().exists()},
            "imports": {"available": imports_count > 0, "files_count": imports_count},
        },
        "distilled_counts": {
            "preferences": len(person.get("preferences", [])),
            "decisions": len(person.get("decisions", [])),
            "projects": len(person.get("projects", [])),
            "open_loops": len(person.get("open_loops", [])),
            "style_notes": len(person.get("style_notes", [])),
        },
        "storage_paths": {
            "memory_dir": str(mem_dir),
            "person_json": str(mem_dir / "person.json"),
            "person_md": str(mem_dir / "person.md"),
        },
    }


def sync_cross_agent_memory(limit: int = 250, distill: bool = True) -> Dict[str, Any]:
    mem_dir, raw_dir, imp_dir = ensure_memory_dirs()
    now_str = _now_iso()
    claude_items = extract_claude_code(limit)
    hermes_items = extract_hermes(limit)
    codex_items = extract_codex(limit // 2)
    ares_items = extract_ares_journal(limit)
    import_items = extract_export_drops(limit)
    all_raw = claude_items + hermes_items + codex_items + ares_items + import_items
    interesting = filter_high_signal_items(all_raw, max_keep=200)
    corpus_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    corpus_path = raw_dir / f"corpus-{corpus_date}.jsonl"
    with open(corpus_path, "w", encoding="utf-8") as f:
        for it in interesting:
            f.write(json.dumps(it, ensure_ascii=False) + chr(10))
    source_counts = dict(Counter(it["source"] for it in all_raw))
    existing_person = load_json(mem_dir / "person.json", {})
    new_facts = distill_facts_from_corpus(interesting) if distill else {}

    def merge_categories(cat_key: str):
        existing_list = existing_person.get(cat_key, [])
        new_list = new_facts.get(cat_key, [])
        seen = set()
        merged = []
        for item in existing_list + new_list:
            t = (item.get("text") if isinstance(item, dict) else str(item)).strip()
            sig = t.lower()
            if sig and sig not in seen:
                seen.add(sig)
                if isinstance(item, dict):
                    merged.append(item)
                else:
                    merged.append({"text": t, "source": "legacy", "at": now_str})
        return merged[-50:]

    updated_person = {
        "updated": now_str,
        "source_stats": source_counts,
        "preferences": merge_categories("preferences"),
        "decisions": merge_categories("decisions"),
        "projects": merge_categories("projects"),
        "open_loops": merge_categories("open_loops"),
        "style_notes": merge_categories("style_notes"),
    }
    save_json(mem_dir / "person.json", updated_person)
    md_content = generate_person_md(updated_person)
    with open(mem_dir / "person.md", "w", encoding="utf-8") as f:
        f.write(md_content)
    state = {
        "last_ingest": now_str,
        "counts_all": source_counts,
        "interesting_count": len(interesting),
        "corpus_path": str(corpus_path),
    }
    save_json(mem_dir / "state.json", state)
    return {
        "status": "success",
        "timestamp": now_str,
        "raw_items_ingested": len(all_raw),
        "high_signal_items": len(interesting),
        "source_breakdown": source_counts,
        "distilled_facts": {
            "preferences": len(updated_person["preferences"]),
            "decisions": len(updated_person["decisions"]),
            "projects": len(updated_person["projects"]),
            "open_loops": len(updated_person["open_loops"]),
            "style_notes": len(updated_person["style_notes"]),
        },
        "output_files": {
            "person_json": str(mem_dir / "person.json"),
            "person_md": str(mem_dir / "person.md"),
            "corpus": str(corpus_path),
        },
    }


def get_cross_agent_profile() -> Dict[str, Any]:
    mem_dir, _, _ = ensure_memory_dirs()
    person = load_json(mem_dir / "person.json", {})
    md_path = mem_dir / "person.md"
    md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else generate_person_md(person)
    return {"profile": person, "markdown": md_text}
