"""ARES Operating Modes — Cognitive State definitions and schemas."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class CognitiveMode(str, Enum):
    """Cognitive operating modes for the ARES autonomous agent."""
    STANDBY = "standby"      # 💤 Passive listening, triage & low-power event monitoring
    FOCUS = "focus"          # 🎯 Deep autonomous execution loop (Plan -> Edit -> Test -> Verify)
    WONDERING = "wondering"  # 🌌 Open-ended codebase exploration, architecture discovery & curiosity
    DREAM = "dream"          # 🌙 Background memory consolidation, AST indexing & knowledge graph synthesis
    RESEARCH = "research"    # 🔬 Deep multi-source analysis, doc synthesis & comparative investigations
    AUDIT = "audit"          # 🛡️ Security inspection, doctrine compliance & quality gate review


# Synonyms and aliases mapping to canonical CognitiveMode
MODE_ALIASES: dict[str, CognitiveMode] = {
    "standby": CognitiveMode.STANDBY,
    "idle": CognitiveMode.STANDBY,
    "sleep": CognitiveMode.STANDBY,
    "focus": CognitiveMode.FOCUS,
    "build": CognitiveMode.FOCUS,
    "code": CognitiveMode.FOCUS,
    "execute": CognitiveMode.FOCUS,
    "wondering": CognitiveMode.WONDERING,
    "wonder": CognitiveMode.WONDERING,
    "explore": CognitiveMode.WONDERING,
    "curiosity": CognitiveMode.WONDERING,
    "dream": CognitiveMode.DREAM,
    "reflect": CognitiveMode.DREAM,
    "synthesis": CognitiveMode.DREAM,
    "research": CognitiveMode.RESEARCH,
    "analyze": CognitiveMode.RESEARCH,
    "investigate": CognitiveMode.RESEARCH,
    "audit": CognitiveMode.AUDIT,
    "review": CognitiveMode.AUDIT,
    "verify": CognitiveMode.AUDIT,
    "security": CognitiveMode.AUDIT,
}


def normalize_mode(raw: str | CognitiveMode) -> CognitiveMode:
    """Normalize a raw mode string or enum into a canonical CognitiveMode."""
    if isinstance(raw, CognitiveMode):
        return raw
    key = str(raw or "").lower().strip()
    match = MODE_ALIASES.get(key)
    if match is not None:
        return match
    try:
        return CognitiveMode(key)
    except ValueError:
        raise ValueError(
            f"Invalid cognitive mode '{raw}'. Supported modes: "
            f"{', '.join(m.value for m in CognitiveMode)}"
        )


@dataclass
class DreamReport:
    """Report generated upon completion of a Dream / Wondering synthesis cycle."""
    cycle_id: str
    started_at: float
    completed_at: float
    workspaces_scanned: list[str] = field(default_factory=list)
    symbols_indexed: int = 0
    files_analyzed: int = 0
    memories_consolidated: int = 0
    insights: list[str] = field(default_factory=list)
    status: str = "completed"
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        return max(0.0, (self.completed_at - self.started_at) * 1000.0)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["duration_ms"] = round(self.duration_ms, 2)
        return data


@dataclass
class FocusExecutionResult:
    """Result of an autonomous Focus Mode problem-solving cycle."""
    session_id: str
    goal: str
    started_at: float
    completed_at: float
    steps_total: int = 0
    steps_completed: int = 0
    edits_applied: int = 0
    tests_run: int = 0
    tests_passed: bool = True
    test_output: str = ""
    status: str = "completed"
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        return max(0.0, (self.completed_at - self.started_at) * 1000.0)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["duration_ms"] = round(self.duration_ms, 2)
        return data


@dataclass
class ModeState:
    """Persistent cognitive state across ARES sessions."""
    current_mode: CognitiveMode = CognitiveMode.STANDBY
    previous_mode: CognitiveMode = CognitiveMode.STANDBY
    switched_at: float = field(default_factory=time.time)
    auto_dream_enabled: bool = True
    auto_dream_interval_seconds: int = 1800  # 30 minutes
    last_dream_at: float | None = None
    dreams_count: int = 0
    focus_runs_count: int = 0
    active_focus_session: str | None = None
    last_dream_report: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "current_mode": self.current_mode.value,
            "previous_mode": self.previous_mode.value,
            "switched_at": self.switched_at,
            "auto_dream_enabled": self.auto_dream_enabled,
            "auto_dream_interval_seconds": self.auto_dream_interval_seconds,
            "last_dream_at": self.last_dream_at,
            "dreams_count": self.dreams_count,
            "focus_runs_count": self.focus_runs_count,
            "active_focus_session": self.active_focus_session,
            "last_dream_report": self.last_dream_report,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModeState:
        current_str = data.get("current_mode", "standby")
        prev_str = data.get("previous_mode", "standby")
        try:
            current_mode = normalize_mode(current_str)
        except ValueError:
            current_mode = CognitiveMode.STANDBY
        try:
            prev_mode = normalize_mode(prev_str)
        except ValueError:
            prev_mode = CognitiveMode.STANDBY

        return cls(
            current_mode=current_mode,
            previous_mode=prev_mode,
            switched_at=float(data.get("switched_at", time.time())),
            auto_dream_enabled=bool(data.get("auto_dream_enabled", True)),
            auto_dream_interval_seconds=int(data.get("auto_dream_interval_seconds", 1800)),
            last_dream_at=data.get("last_dream_at"),
            dreams_count=int(data.get("dreams_count", 0)),
            focus_runs_count=int(data.get("focus_runs_count", 0)),
            active_focus_session=data.get("active_focus_session"),
            last_dream_report=data.get("last_dream_report"),
        )
