"""SI character sheet survives worker / model swaps.

Identity lives in ``<ares_home>/si/identity.json``. Working memory is
MEMORY.md / USER.md plus ``retrieve_memories()`` from the SI store.
Changing the worker id must not change the SI name or drop a stored fact.
No live Hermes (or any live worker) is required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import api.memory_store as memory_store
import api.profiles as profiles
from api.si.context_compiler import compile_context
from api.si.identity import SIIdentityConfig, get_active_ares_home, load_identity, save_identity
from api.si.memory import ingest_memory
from api.si.types import PERSONAL


FACT = "The owner's cat is named PixelSevenNine."
IDENTITY_NAME = "AthenaCharacterSheet"


def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point identity, profile files, and the SI journal at a tmp ARES home."""
    home = tmp_path / "ares-home"
    home.mkdir()
    (home / "si").mkdir()
    (home / "memories").mkdir()
    (home / "journal").mkdir()
    monkeypatch.setenv("ARES_HOME", str(home))
    monkeypatch.setenv("ARES_BASE_HOME", str(home))
    monkeypatch.setattr(profiles, "get_active_ares_home", lambda: home)
    return home


def _sheet_text(briefing) -> str:
    parts = [briefing.si_identity.name or ""]
    parts.extend(item.content for item in briefing.user_context)
    parts.extend(mem.content for mem in briefing.relevant_memories)
    return "\n".join(parts)


def test_canonical_identity_path_is_si_identity_json(tmp_path, monkeypatch):
    home = _isolate_home(tmp_path, monkeypatch)
    from api.si.identity import _identity_path

    assert get_active_ares_home() == home
    assert _identity_path() == home / "si" / "identity.json"
    assert ".hermes" not in str(_identity_path())


def test_character_sheet_survives_worker_swap(tmp_path, monkeypatch):
    """Write a fact, swap worker id, next briefing keeps identity name + fact."""
    home = _isolate_home(tmp_path, monkeypatch)

    save_identity(SIIdentityConfig(
        name=IDENTITY_NAME,
        owner_name="Matthew",
        mission="Stay continuous across worker swaps.",
    ))
    loaded = load_identity()
    assert loaded.name == IDENTITY_NAME
    assert (home / "si" / "identity.json").is_file()

    # Profile working memory (not identity).
    memory_store.write_memory("memory", FACT)
    memory_store.write_memory("user", "Owner prefers being called Matthew.")

    # Dual SOUL remnants must not become identity.
    (home / "SOUL.md").write_text("SOUL file is style, not identity.", encoding="utf-8")
    (home / "memories" / "SOUL.md").write_text("Dual soul must not be identity.", encoding="utf-8")

    from api.journal.schema import init_db

    init_db()
    memory_id = ingest_memory(
        "preference",
        FACT,
        metadata={"title": "cat name"},
        sensitivity=PERSONAL,
        is_decision=True,
    )
    assert memory_id.startswith("mem_")

    query = f"What is the name of the owner's cat? Remember PixelSevenNine."
    first = compile_context(query, target_worker_id="jaeger_local")
    second = compile_context(query, target_worker_id="grok_local")

    for briefing, worker in ((first, "jaeger_local"), (second, "grok_local")):
        assert briefing.si_identity.name == IDENTITY_NAME, worker
        text = _sheet_text(briefing)
        assert "PixelSevenNine" in text, f"{worker} lost the SI fact: {text!r}"
        assert "Dual soul must not be identity" not in (briefing.si_identity.name or "")
        # Profile files loaded as working memory, not as identity.
        assert any(item.source_id == "MEMORY.md" for item in briefing.user_context), worker
        assert any(item.source_id == "USER.md" for item in briefing.user_context), worker

    assert first.si_identity.name == second.si_identity.name
    assert "PixelSevenNine" in _sheet_text(first)
    assert "PixelSevenNine" in _sheet_text(second)
