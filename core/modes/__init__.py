"""ARES Cognitive Operating Modes subsystem.

Defines the three cognitive states of ARES:
1. STANDBY: Passive, event-driven listening & monitoring.
2. FOCUS: Deep autonomous problem-solving & verification loop.
3. WONDER (Dream): Background synthesis, memory consolidation, and AST repomap generation.
"""

from __future__ import annotations

from .operating_modes import CognitiveMode, ModeState, DreamReport, FocusExecutionResult
from .mode_manager import ModeManager, get_mode_manager

__all__ = [
    "CognitiveMode",
    "ModeState",
    "DreamReport",
    "FocusExecutionResult",
    "ModeManager",
    "get_mode_manager",
]
